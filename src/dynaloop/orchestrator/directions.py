"""⑥ → ①: turn descriptive Statistical Feedback into the next policy version.

The statistical feedback never edits a frozen object and never bypasses the
training engine. It only tilts the (already updated) exploration policy away
from the weakest choices, producing one more immutable policy version whose
full parameter set is written into the round spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from dynaloop.research_engine import ExplorationPolicy
from dynaloop.statistical_uncertainty_engine import StatisticalFeedback


@runtime_checkable
class DirectionAdapter(Protocol):
    name: str

    def spec(self) -> dict[str, Any]: ...

    def adapt(
        self, policy: ExplorationPolicy, feedback: StatisticalFeedback
    ) -> tuple[ExplorationPolicy, dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class NoOpDirectionAdapter:
    """Explicitly disable the feedback edge without special-casing the loop."""

    name: str = "noop"

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "enabled": False}

    def adapt(
        self, policy: ExplorationPolicy, feedback: StatisticalFeedback
    ) -> tuple[ExplorationPolicy, dict[str, Any]]:
        return policy, {
            **self.spec(),
            "applied_keys": [],
            "skipped_keys": list(feedback.new_directions),
            "policy_before_version": policy.version,
            "policy_after_version": policy.version,
            "feedback_fingerprint": feedback.fingerprint(),
        }


@dataclass(frozen=True, slots=True)
class ReliabilityDirectionAdapter:
    """Down-weight the weakest non-selected choices by a fixed factor."""

    strength: float = 0.25
    name: str = "reliability_downweight"

    def __post_init__(self) -> None:
        if not 0 <= float(self.strength) < 1:
            raise ValueError("strength must lie in [0, 1).")

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": True,
            "strength": self.strength,
            "rule": "weight *= (1 - strength) for keys named by StatisticalFeedback.new_directions",
            "descriptive_only": True,
        }

    def adapt(
        self, policy: ExplorationPolicy, feedback: StatisticalFeedback
    ) -> tuple[ExplorationPolicy, dict[str, Any]]:
        keys = tuple(dict.fromkeys(feedback.new_directions))
        applied = tuple(key for key in keys if key in policy.weights)
        skipped = tuple(key for key in keys if key not in policy.weights)
        after = policy
        if applied:
            weights = {
                key: value * (1.0 - self.strength) if key in applied else value
                for key, value in policy.weights.items()
            }
            after = policy.with_weights(weights)
        detail = {
            **self.spec(),
            "applied_keys": list(applied),
            "skipped_keys": list(skipped),
            "policy_before_version": policy.version,
            "policy_after_version": after.version,
            "policy_before_fingerprint": policy.fingerprint(),
            "policy_after_fingerprint": after.fingerprint(),
            "feedback_fingerprint": feedback.fingerprint(),
        }
        return after, detail
