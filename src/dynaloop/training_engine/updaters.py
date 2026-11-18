"""Policy updaters: the single-module update semantics of stage 2 / ⑤.

The default updater is Hedge / EXP3-style multiplicative weights (Freund &
Schapire): ``w_i <- w_i * exp(lr * A_i)`` for group-relative advantages ``A_i``.
``GRPOGroupUpdater`` is a real, interchangeable alternative that adds a KL
penalty to the initial policy (the discrete-distribution counterpart of TRL's
``beta * KL(p || p_ref)`` term). Neither is a stub; there is no LM weight update.
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from dynaloop.research_engine.exploration import ExplorationPolicy, PolicyError

UPDATER_SCHEMA_VERSION = 1


@runtime_checkable
class PolicyUpdater(Protocol):
    """Replacement point for a future GRPO/RL trainer."""

    name: str

    def spec(self) -> dict[str, Any]: ...

    def update(
        self,
        policy: ExplorationPolicy,
        choices: Sequence[str],
        advantages: Sequence[float],
    ) -> ExplorationPolicy: ...


def _scores(
    choices: Sequence[str],
    advantages: Sequence[float],
) -> dict[str, float]:
    if len(choices) != len(advantages):
        raise PolicyError("choices and advantages must have the same length.")
    if not choices:
        raise PolicyError("Cannot update a policy from an empty group.")
    totals: dict[str, list[float]] = {}
    for choice, advantage in zip(choices, advantages):
        if not math.isfinite(float(advantage)):
            raise PolicyError("Advantages must be finite.")
        totals.setdefault(choice, []).append(float(advantage))
    return {key: sum(values) / len(values) for key, values in totals.items()}


def _renormalise(weights: dict[str, float], size: int) -> dict[str, float]:
    total = sum(weights.values())
    if not math.isfinite(total) or total <= 0:
        raise PolicyError("The policy update produced non-finite weights.")
    return {key: value / total * size for key, value in weights.items()}


@dataclass(frozen=True, slots=True)
class RewardWeightedUpdater:
    """Hedge / EXP3 multiplicative weights on group-relative advantages."""

    name: str = "reward_weighted"

    def spec(self) -> dict[str, Any]:
        return {
            "schema_version": UPDATER_SCHEMA_VERSION,
            "name": self.name,
            "rule": "w_i <- w_i * exp(learning_rate * advantage_i); renormalise",
            "learning_rate": "ExplorationPolicy.learning_rate",
            "kl_beta": 0.0,
        }

    def update(
        self,
        policy: ExplorationPolicy,
        choices: Sequence[str],
        advantages: Sequence[float],
    ) -> ExplorationPolicy:
        scores = _scores(choices, advantages)
        unknown = [key for key in scores if key not in policy.weights]
        if unknown:
            raise PolicyError(f"Choices are outside the policy space: {sorted(unknown)[:5]}.")
        updated = dict(policy.weights)
        for key, score in scores.items():
            updated[key] = updated[key] * math.exp(policy.learning_rate * score)
        return policy.with_weights(_renormalise(updated, len(updated)))


@dataclass(frozen=True, slots=True)
class GRPOGroupUpdater:
    """Group-relative advantages plus a KL-to-prior penalty (TRL ``beta``).

    On a categorical policy the KL gradient reduces to ``log(w / w_prior)``;
    ``beta=0`` reproduces ``RewardWeightedUpdater``. This is a discrete
    approximation, not TRL's per-token KL against a reference language model.
    """

    beta: float = 0.05
    prior: Mapping[str, float] | None = None
    name: str = "grpo_group"

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.beta)) or self.beta < 0:
            raise PolicyError("beta must be a finite non-negative number.")

    def spec(self) -> dict[str, Any]:
        return {
            "schema_version": UPDATER_SCHEMA_VERSION,
            "name": self.name,
            "rule": "w_i <- w_i * exp(learning_rate * (advantage_i - beta * log(w_i / prior_i)))",
            "learning_rate": "ExplorationPolicy.learning_rate",
            "kl_beta": self.beta,
            "prior": "initial policy" if self.prior is None else "explicit prior",
        }

    def update(
        self,
        policy: ExplorationPolicy,
        choices: Sequence[str],
        advantages: Sequence[float],
    ) -> ExplorationPolicy:
        scores = _scores(choices, advantages)
        prior = dict(self.prior or policy.weights)
        unknown = [key for key in scores if key not in policy.weights or key not in prior]
        if unknown:
            raise PolicyError(f"Choices are outside the policy/prior space: {sorted(unknown)[:5]}.")
        updated = dict(policy.weights)
        for key, score in scores.items():
            if prior[key] <= 0 or updated[key] <= 0:
                raise PolicyError("Prior and policy weights must be positive.")
            penalty = float(self.beta) * math.log(updated[key] / prior[key])
            updated[key] = updated[key] * math.exp(policy.learning_rate * (score - penalty))
        return policy.with_weights(_renormalise(updated, len(updated)))


UPDATER_REGISTRY: dict[str, type] = {
    "reward_weighted": RewardWeightedUpdater,
    "grpo_group": GRPOGroupUpdater,
}


def register_updater(name: str, updater_type: type) -> None:
    if not name:
        raise PolicyError("An updater name must be a non-empty string.")
    UPDATER_REGISTRY[name] = updater_type


def build_updater(name_or_path: str, **kwargs: Any) -> PolicyUpdater:
    if "." in name_or_path:
        module_name, class_name = name_or_path.rsplit(".", 1)
        updater_type = getattr(importlib.import_module(module_name), class_name)
    elif name_or_path in UPDATER_REGISTRY:
        updater_type = UPDATER_REGISTRY[name_or_path]
    else:
        raise PolicyError(f"Unknown policy updater: {name_or_path!r}.")
    updater = updater_type(**kwargs)
    if not isinstance(updater, PolicyUpdater):
        raise PolicyError(f"{name_or_path!r} does not implement PolicyUpdater.")
    return updater
