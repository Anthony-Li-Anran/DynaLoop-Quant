"""Small recurrent-depth predictor. Requires the optional ``brain`` extra."""
from dataclasses import dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class BrainConfig:
    features: tuple[str, ...]
    window: int = 64
    width: int = 128
    heads: int = 4
    blocks: int = 2
    loops: int = 4
    seed: int = 7
    normalization: str = "window"

    def __post_init__(self):
        object.__setattr__(self, "features", tuple(self.features))
        if not self.features or len(set(self.features)) != len(self.features):
            raise ValueError("features must be nonempty and unique")
        if any(not isinstance(f, str) or not f for f in self.features):
            raise ValueError("feature names must be nonempty strings")
        for name in ("window", "width", "heads", "blocks", "loops"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.width % self.heads:
            raise ValueError("width must be divisible by heads")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("seed must be an integer in [0, 2**63)")
        if self.normalization not in {"window", "none"}:
            raise ValueError("normalization must be window or none")


class LoopedTransformer(nn.Module):
    """Window-to-one prediction; all tokens precede the prediction timestamp.

    Shared blocks recur in depth, not in market time. Dropout is disabled for
    deterministic CPU streaming and replay. No cross-window hidden state exists.
    """

    def __init__(self, config: BrainConfig):
        super().__init__()
        self.config = config
        # Construction must not reseed the application's global generator.
        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(config.seed)
            self.embedding = nn.Linear(len(config.features), config.width)
            self.position = nn.Parameter(torch.randn(config.window, config.width) * .02)
            self.core = nn.ModuleList([
                nn.TransformerEncoderLayer(config.width, config.heads,
                    dim_feedforward=4 * config.width, dropout=0.,
                    activation="gelu", batch_first=True, norm_first=True)
                for _ in range(config.blocks)
            ])
            self.injection_norm = nn.LayerNorm(config.width)
            self.head = nn.Sequential(nn.LayerNorm(config.width), nn.Linear(config.width, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or tuple(x.shape[1:]) != (self.config.window, len(self.config.features)):
            raise ValueError("expected [batch, configured window, configured features]")
        if not torch.isfinite(x).all():
            raise ValueError("input must be finite")
        # Per-window normalization uses no future observations and has no mutable
        # running statistics. Stored raw windows replay with identical semantics.
        normalized = x
        if self.config.normalization == "window":
            stable = x.double()
            mean = stable.mean(dim=1, keepdim=True)
            scale = stable.std(dim=1, keepdim=True, correction=0).clamp_min(1e-6)
            normalized = ((stable - mean) / scale).to(x.dtype)
        e = self.embedding(normalized) + self.position
        h = torch.zeros_like(e)
        for _ in range(self.config.loops):
            h = self.injection_norm(h + e)
            for block in self.core:
                h = block(h)
        return self.head(h[:, -1]).squeeze(-1)
