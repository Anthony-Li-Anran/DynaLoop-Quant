"""Exploration policy: the only loop state that stage 2 is allowed to update.

A policy is a categorical distribution over a generator's choice keys. Weights
are positive multiplicative weights (Hedge / EXP3 style, Freund & Schapire), and
``softmax(log(w) / temperature)`` mixed with an exploration floor gives the
sampling probabilities. The object is frozen: every update creates a new
``version`` instead of overwriting a previous spec.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np

from dynaloop.research_engine.spec import fingerprint

EXPLORATION_SCHEMA_VERSION = 1
_MIN_WEIGHT = 1e-12
_VALID_TEMPERATURES = (0.0, math.inf)


class PolicyError(ValueError):
    """The policy or its choice space is inconsistent."""


def _finite_positive(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise PolicyError(f"{label} must be a finite positive number.")
    return number


@dataclass(frozen=True, slots=True)
class ExplorationPolicy:
    """Immutable, versioned categorical policy over generator choice keys."""

    weights: Mapping[str, float]
    version: int = 0
    learning_rate: float = 0.35
    exploration_floor: float = 0.02
    temperature: float = 1.0

    def __post_init__(self) -> None:
        if not self.weights:
            raise PolicyError("A policy needs at least one choice key.")
        clean: dict[str, float] = {}
        for key, value in self.weights.items():
            if not isinstance(key, str) or not key:
                raise PolicyError("Choice keys must be non-empty strings.")
            clean[key] = _finite_positive(value, f"weight[{key!r}]")
        object.__setattr__(self, "weights", MappingProxyType(clean))
        if not isinstance(self.version, int) or self.version < 0:
            raise PolicyError("version must be a non-negative integer.")
        _finite_positive(self.learning_rate, "learning_rate")
        _finite_positive(self.temperature, "temperature")
        floor = float(self.exploration_floor)
        if not math.isfinite(floor) or not 0 <= floor < 1:
            raise PolicyError("exploration_floor must be in [0, 1).")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EXPLORATION_SCHEMA_VERSION,
            "version": self.version,
            "weights": dict(sorted(self.weights.items())),
            "learning_rate": self.learning_rate,
            "exploration_floor": self.exploration_floor,
            "temperature": self.temperature,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())

    def probabilities(self, keys: Sequence[str]) -> np.ndarray:
        """Softmax over ``keys`` with a uniform exploration-floor mixture."""
        if not keys:
            raise PolicyError("Cannot build probabilities over an empty choice space.")
        missing = [key for key in keys if key not in self.weights]
        if missing:
            raise PolicyError(f"Policy is missing choice keys: {sorted(missing)[:5]}.")
        logits = np.log(np.array([self.weights[key] for key in keys], dtype=float))
        scaled = logits / self.temperature
        scaled -= scaled.max()
        exponential = np.exp(scaled)
        distribution = exponential / exponential.sum()
        floor = float(self.exploration_floor)
        return (1.0 - floor) * distribution + floor / len(keys)

    def with_weights(self, weights: Mapping[str, float]) -> "ExplorationPolicy":
        """Return the next immutable version; the current object never changes."""
        return replace(self, weights=dict(weights), version=self.version + 1)


def uniform_policy(keys: Sequence[str], **kwargs: Any) -> ExplorationPolicy:
    if not keys or len(set(keys)) != len(keys):
        raise PolicyError("Choice keys must be a non-empty sequence of unique strings.")
    return ExplorationPolicy(weights={key: 1.0 for key in keys}, **kwargs)
