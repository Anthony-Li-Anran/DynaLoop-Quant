"""Diffusion rehearsal and delayed, prequential shadow promotion."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from dynaloop.training_engine.diffusion import ConditionalDiffusion
from dynaloop.training_engine.sequences import FeatureScaler, generated_samples, CONTEXT
from dynaloop.training_engine.wake import WakeLearner


@dataclass(frozen=True)
class SleepConfig:
    interval: int = 63
    shadow_labels: int = 32
    samples: int = 128
    train_steps: int = 25
    synthetic_weight: float = .2
    generator_updates: int = 50

    def __post_init__(self):
        for key in ("interval", "shadow_labels", "samples", "train_steps", "generator_updates"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f"{key} must be a positive integer")
        if not 0 <= self.synthetic_weight <= 1:
            raise ValueError("synthetic_weight must be in [0,1]")


class SleepController:
    def __init__(self, learner: WakeLearner, generator: ConditionalDiffusion, scaler: FeatureScaler,
                 config: SleepConfig = SleepConfig(), *, seed: int = 7):
        self.learner, self.generator, self.scaler, self.config = learner, generator, scaler, config
        self.rng = np.random.default_rng(seed)
        self.candidate = None
        self.shadow = {}
        self.errors = []
        self.log = []
        self.lineage = 0
        self.candidate_id = 0

    def propose(self, paths: np.ndarray, *, timestamp: str, max_maturity: str) -> dict:
        """Caller supplies only real paths whose labels matured by timestamp."""
        if max_maturity > timestamp:
            raise ValueError("Sleep received future labels")
        if self.candidate is not None:
            raise ValueError("a shadow candidate is already active")
        if len(self.learner.replay) < 2:
            raise ValueError("Sleep requires real replay")
        fit = self.generator.fit(paths, updates=self.config.generator_updates)
        indices = self.rng.integers(len(paths), size=self.config.samples)
        generated, diagnostics = self.generator.sample(paths[indices, :CONTEXT])
        event = dict(kind="sleep", timestamp=timestamp, real_paths=len(paths),
            max_maturity=max_maturity, generator=fit, diagnostics=diagnostics,
            parent_lineage=self.lineage)
        if len(generated) < 8:
            event["status"] = "insufficient_valid_paths"
            self.log.append(event)
            return event
        x, y = generated_samples(generated, self.learner.model.config.window, self.learner.config.horizon)
        x = self.scaler.transform(x)
        candidate = deepcopy(self.learner)
        # Replay entries remain exclusively real. Synthetic samples never leak
        # into future Wake replay or the generator's real training dataset.
        real = list(candidate.replay)
        losses = []
        candidate.model.train()
        for _ in range(self.config.train_steps):
            ri = self.rng.integers(len(real), size=candidate.config.batch_size)
            si = self.rng.integers(len(x), size=candidate.config.batch_size)
            rx = torch.stack([real[i][0] for i in ri]).to(candidate.device)
            ry = torch.tensor([real[i][1]*candidate.config.target_scale for i in ri],
                              dtype=torch.float32, device=candidate.device)
            sx = torch.as_tensor(x[si], device=candidate.device)
            sy = torch.as_tensor(y[si] / 100 * candidate.config.target_scale, device=candidate.device)
            real_loss = F.huber_loss(candidate.model(rx), ry, delta=candidate.config.huber_delta)
            synthetic_loss = F.huber_loss(candidate.model(sx), sy, delta=candidate.config.huber_delta)
            loss = real_loss + self.config.synthetic_weight * synthetic_loss
            if not torch.isfinite(loss):
                raise FloatingPointError("nonfinite Sleep loss")
            candidate.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(candidate.model.parameters(), candidate.config.gradient_clip,
                                          error_if_nonfinite=True)
            candidate.optimizer.step()
            candidate.version += 1
            losses.append(float(loss.detach()))
        self.candidate = candidate
        self.candidate_id += 1
        self.shadow, self.errors = {}, []
        event.update(status="shadow", candidate_id=self.candidate_id, mean_loss=float(np.mean(losses)))
        self.log.append(event)
        return event

    def observe(self, timestamp: str, close: float, features: dict, *, symbol: str):
        lineage = self.lineage
        incumbent = self.learner.observe(timestamp, close, features, symbol=symbol)
        if self.candidate is not None:
            challenger = self.candidate.observe(timestamp, close, features, symbol=symbol)
            if incumbent.prediction is not None and challenger.prediction is not None:
                self.shadow[timestamp] = (incumbent.prediction, challenger.prediction)
            matured = incumbent.matured_timestamp
            if matured in self.shadow:
                left, right = self.shadow.pop(matured)
                target = incumbent.realized_return
                self.errors.append(((left-target)**2, (right-target)**2))
            if len(self.errors) >= self.config.shadow_labels:
                errors = np.asarray(self.errors)
                promote = bool(errors[:, 1].mean() < errors[:, 0].mean())
                self.log.append(dict(kind="gate", timestamp=timestamp, candidate_id=self.candidate_id,
                    observations=len(errors), incumbent_mse=float(errors[:, 0].mean()),
                    candidate_mse=float(errors[:, 1].mean()), promoted=promote))
                if promote:
                    self.learner = self.candidate
                    self.lineage += 1
                self.candidate = None
                self.shadow, self.errors = {}, []
        # Prediction belongs to the incumbent BEFORE today's promotion.
        return incumbent, lineage

    def checkpoint_metadata(self):
        return dict(config=self.config.__dict__, lineage=self.lineage, candidate_id=self.candidate_id,
                    shadow=self.shadow, errors=self.errors, log=self.log, rng=self.rng.bit_generator.state)

    def save(self, directory):
        """Immutable checkpoint directory; manifest is written only on completion."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        self.learner.save(directory/"incumbent.pt")
        if self.candidate is not None:
            self.candidate.save(directory/"candidate.pt")
        torch.save(self.generator.state_dict(), directory/"generator.pt")
        metadata = dict(format_version=1, **self.checkpoint_metadata(), scaler=self.scaler.to_dict(),
                        has_candidate=self.candidate is not None)
        (directory/"complete.json").write_text(json.dumps(metadata, allow_nan=False), encoding="utf-8")

    @classmethod
    def load(cls, directory, *, device="cpu"):
        directory = Path(directory)
        metadata = json.loads((directory/"complete.json").read_text(encoding="utf-8"))
        if metadata["format_version"] != 1:
            raise ValueError("unsupported Sleep checkpoint")
        learner = WakeLearner.load(directory/"incumbent.pt", device=device)
        generator = ConditionalDiffusion.from_state_dict(
            torch.load(directory/"generator.pt", map_location="cpu", weights_only=True), device=device)
        scaler = FeatureScaler(np.asarray(metadata["scaler"]["mean"], dtype=np.float32),
                               np.asarray(metadata["scaler"]["scale"], dtype=np.float32))
        result = cls(learner, generator, scaler, SleepConfig(**metadata["config"]))
        if metadata["has_candidate"]:
            result.candidate = WakeLearner.load(directory/"candidate.pt", device=device)
        result.lineage, result.candidate_id = metadata["lineage"], metadata["candidate_id"]
        result.shadow, result.errors, result.log = metadata["shadow"], metadata["errors"], metadata["log"]
        result.rng.bit_generator.state = metadata["rng"]
        return result
