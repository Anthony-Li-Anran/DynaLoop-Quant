"""One frozen configuration for a complete six-stage loop run."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from dynaloop.research_engine.spec import fingerprint

ORCHESTRATOR_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class LoopConfig:
    """Every free parameter; nothing is read from ambient state."""

    symbol: str = "TEST"
    start: str = "2024-01-01"
    end: str = "2024-02-10"
    seed: int = 7
    rounds: int = 3
    group_size: int = 6
    features: tuple[str, ...] = ("open", "high", "low", "close", "volume")
    windows: tuple[int, ...] = (5, 10)
    generator: str = "template"
    bias_magnitude: float = 0.0
    bias_mode: str = "additive"
    proxy_reps: int = 120
    proxy_block_size: int = 4
    statistical_reps: int = 120
    statistical_block_size: int = 5
    alpha: float = 0.1
    direction_strength: float = 0.25
    experiment_id: str | None = "dynaloop-loop"

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.symbol, self.start, self.end)):
            raise ValueError("symbol, start and end are required.")
        if self.start > self.end:
            raise ValueError("start must not follow end (inclusive window).")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer.")
        for label, value in (
            ("rounds", self.rounds),
            ("group_size", self.group_size),
            ("proxy_reps", self.proxy_reps),
            ("proxy_block_size", self.proxy_block_size),
            ("statistical_reps", self.statistical_reps),
            ("statistical_block_size", self.statistical_block_size),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{label} must be a positive integer.")
        if not self.features or not self.windows:
            raise ValueError("features and windows cannot be empty.")
        object.__setattr__(self, "features", tuple(self.features))
        object.__setattr__(self, "windows", tuple(self.windows))
        if any(not isinstance(value, str) or not value.isidentifier() for value in self.features):
            raise ValueError("features must contain valid column identifiers.")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in self.windows):
            raise ValueError("windows must contain positive integers.")
        if self.proxy_reps < 10 or self.statistical_reps < 20:
            raise ValueError("proxy_reps must be >= 10 and statistical_reps >= 20.")
        if not math.isfinite(float(self.bias_magnitude)):
            raise ValueError("bias_magnitude must be finite.")
        if not 0 < float(self.alpha) < 1:
            raise ValueError("alpha must lie in (0, 1).")
        if not 0 <= float(self.direction_strength) < 1:
            raise ValueError("direction_strength must lie in [0, 1).")
        if self.bias_mode not in ("additive", "multiplicative"):
            raise ValueError("bias_mode must be 'additive' or 'multiplicative'.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ORCHESTRATOR_SCHEMA_VERSION,
            "symbol": self.symbol,
            "start": self.start,
            "end": self.end,
            "seed": self.seed,
            "rounds": self.rounds,
            "group_size": self.group_size,
            "features": list(self.features),
            "windows": list(self.windows),
            "generator": self.generator,
            "bias_magnitude": self.bias_magnitude,
            "bias_mode": self.bias_mode,
            "proxy_reps": self.proxy_reps,
            "proxy_block_size": self.proxy_block_size,
            "statistical_reps": self.statistical_reps,
            "statistical_block_size": self.statistical_block_size,
            "alpha": self.alpha,
            "direction_strength": self.direction_strength,
            "experiment_id": self.experiment_id,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())
