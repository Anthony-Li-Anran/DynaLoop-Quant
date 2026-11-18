"""Single-stream Wake learner with delayed labels and bounded CPU replay.

Observe is synchronous and not thread-safe. One owner serializes observations
and checkpoints. Call after the bar closes; signals may only execute afterward.
"""
from collections import deque
from dataclasses import asdict, dataclass
import math
import os
from pathlib import Path
import random
import tempfile

import torch
from torch.nn import functional as F

from dynaloop.model.brain import BrainConfig, LoopedTransformer


@dataclass(frozen=True)
class WakeConfig:
    horizon: int = 1
    replay_capacity: int = 512
    batch_size: int = 16
    learning_rate: float = 1e-4
    gradient_clip: float = 1.0
    huber_delta: float = .01
    weight_decay: float = .01
    target_scale: float = 1.0

    def __post_init__(self):
        for name in ("horizon", "replay_capacity", "batch_size"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("learning_rate", "gradient_clip", "huber_delta", "target_scale"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if isinstance(self.weight_decay, bool) or not math.isfinite(self.weight_decay) or self.weight_decay < 0:
            raise ValueError("weight_decay must be finite and nonnegative")


@dataclass(frozen=True)
class WakeEvent:
    timestamp: str
    prediction: float | None
    prediction_version: int
    version_after: int
    matured_timestamp: str | None
    realized_return: float | None
    loss: float | None


class WakeLearner:
    def __init__(self, brain: BrainConfig, config: WakeConfig = WakeConfig(), *, symbol: str,
                 device: str = "cpu"):
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol is required")
        self.device = torch.device(device)
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA requested but unavailable")
        self.model = LoopedTransformer(brain).to(self.device)
        self.config = config
        self.symbol = symbol
        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=config.learning_rate,
                                          weight_decay=config.weight_decay)
        self.version = 0
        self.count = 0
        self.last_timestamp = None
        self.history = deque(maxlen=brain.window)
        self.pending = deque()
        self.replay = deque(maxlen=config.replay_capacity)
        self.rng = random.Random(brain.seed)
        self._failed = False

    def observe(self, timestamp: str, close: float, features: dict[str, float], *, symbol: str) -> WakeEvent:
        """Predict first, then update on labels maturing at this observation.

        Timestamps must be canonical, lexically ordered strings in one timezone.
        Horizon counts observations, not calendar intervals. Features must already
        be point-in-time materialized; no backwards fill or revised news allowed.
        """
        if self._failed:
            raise RuntimeError("training failed; restore the last successful checkpoint")
        if symbol != self.symbol:
            raise ValueError("a learner accepts exactly one symbol")
        if not isinstance(timestamp, str) or not timestamp or (
            self.last_timestamp is not None and timestamp <= self.last_timestamp
        ):
            raise ValueError("timestamps must be strictly increasing")
        if isinstance(close, bool) or not math.isfinite(close) or close <= 0:
            raise ValueError("close must be finite and positive")
        if set(features) != set(self.model.config.features):
            raise ValueError("feature schema differs from the model version")
        values = [features[f] for f in self.model.config.features]
        if any(isinstance(v, bool) or not math.isfinite(v) for v in values):
            raise ValueError("features must be finite numbers")
        row = torch.tensor(values, dtype=torch.float32)
        if not torch.isfinite(row).all():
            raise ValueError("features exceed float32 range")
        realized = None
        if self.pending and self.pending[0]["due"] == self.count:
            realized = close / self.pending[0]["close"] - 1.0
            if not math.isfinite(realized) or abs(realized) > 1e30:
                raise ValueError("return outside supported numerical range")
        rows = list(self.history) + [row]
        rows = rows[-self.model.config.window:]
        prediction = None
        window = None
        before = self.version
        if len(rows) == self.model.config.window:
            window = torch.stack(rows)
            self.model.eval()
            with torch.no_grad():
                prediction = float(self.model(window.unsqueeze(0).to(self.device))[0]) / self.config.target_scale
            if not math.isfinite(prediction):
                raise FloatingPointError("nonfinite prediction")
        self.history.append(row)
        self.last_timestamp = timestamp
        index = self.count
        self.count += 1
        matured_timestamp = loss = None
        if self.pending and self.pending[0]["due"] == index:
            # A numerical failure must never allow further observations or a
            # misleading successful checkpoint with partially consumed labels.
            self._failed = True
            sample = self.pending.popleft()
            matured_timestamp = sample["timestamp"]
            item = (sample["window"], realized)
            # Always include the newly matured sample, plus bounded old replay.
            old = self.rng.sample(list(self.replay), min(len(self.replay), self.config.batch_size - 1))
            batch = old + [item]
            self.model.train()
            x = torch.stack([v[0] for v in batch]).to(self.device)
            y = torch.tensor([v[1] * self.config.target_scale for v in batch], dtype=torch.float32, device=self.device)
            self.optimizer.zero_grad(set_to_none=True)
            objective = F.huber_loss(self.model(x), y, delta=self.config.huber_delta)
            if not torch.isfinite(objective):
                raise FloatingPointError("nonfinite training loss")
            objective.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.gradient_clip,
                                          error_if_nonfinite=True)
            self.optimizer.step()
            loss = float(objective.detach())
            self.version += 1
            self.replay.append(item)
            self._failed = False
        if window is not None:
            self.pending.append(dict(due=index + self.config.horizon, timestamp=timestamp,
                                     close=close, window=window))
        return WakeEvent(timestamp, prediction, before, self.version, matured_timestamp, realized, loss)

    def save(self, path: str | Path) -> None:
        """Atomic snapshot includes optimizer, delayed labels, replay and RNG."""
        if self._failed:
            raise RuntimeError("cannot checkpoint failed training; restore a prior checkpoint")
        path = Path(path)
        state = dict(format_version=1, brain=asdict(self.model.config), wake=asdict(self.config),
            symbol=self.symbol, model=self.model.state_dict(), optimizer=self.optimizer.state_dict(),
            version=self.version, count=self.count, last_timestamp=self.last_timestamp,
            history=list(self.history), pending=list(self.pending), replay=list(self.replay),
            rng=self.rng.getstate())
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                torch.save(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    @classmethod
    def load(cls, path: str | Path, *, device: str = "cpu") -> "WakeLearner":
        state = torch.load(path, map_location="cpu", weights_only=True)
        if state["format_version"] != 1:
            raise ValueError("unsupported checkpoint version")
        learner = cls(BrainConfig(**state["brain"]), WakeConfig(**state["wake"]), symbol=state["symbol"], device=device)
        learner.model.load_state_dict(state["model"])
        learner.optimizer.load_state_dict(state["optimizer"])
        learner.version, learner.count = state["version"], state["count"]
        learner.last_timestamp = state["last_timestamp"]
        learner.history.extend(state["history"])
        learner.pending.extend(state["pending"])
        learner.replay.extend(state["replay"])
        learner.rng.setstate(state["rng"])
        return learner
