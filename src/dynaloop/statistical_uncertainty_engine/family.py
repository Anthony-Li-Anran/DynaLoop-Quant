"""Frozen validation families consumed by the statistical engine.

A family is one batch of stage-1 ``FactorEvaluation`` objects over one frozen
window, paired with the Sleep estimations/feedback and the frozen bar records.
Nothing here recomputes a factor or a backtest: the family is a read-only
projection, and the only numeric verdicts are the stage-1 evaluation values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from dynaloop.market_environment import SimulatedEstimation, SimulationFeedback
from dynaloop.research_engine import FactorEvaluation
from dynaloop.research_engine.spec import fingerprint
from dynaloop.training_engine import RewardSpec

STATISTICAL_SCHEMA_VERSION = 1


class StatisticalError(ValueError):
    """Raised when a validation family violates its frozen contract."""


@dataclass(frozen=True, slots=True)
class ValidationFamily:
    """One test family plus the read-only context needed for resampling.

    ``records`` are the same frozen bar records used by the Wake evaluation.
    They are used only to build a null distribution for the selection step;
    no IC, reward or backtest metric is recomputed from them.
    """

    evaluations: tuple[FactorEvaluation, ...]
    round_index: int
    estimations: tuple[SimulatedEstimation, ...] = ()
    feedback: SimulationFeedback | None = None
    records: tuple[Mapping[str, Any], ...] = ()
    choices: tuple[tuple[str, str], ...] = ()
    history: tuple[Mapping[str, float | None], ...] = ()
    reward_spec: RewardSpec = field(default_factory=RewardSpec)

    def __post_init__(self) -> None:
        if not self.evaluations:
            raise StatisticalError("A validation family needs at least one evaluation.")
        if not isinstance(self.round_index, int) or self.round_index < 0:
            raise StatisticalError("round_index must be a non-negative integer.")
        if any(not isinstance(item, FactorEvaluation) for item in self.evaluations):
            raise StatisticalError("Every family member must be a FactorEvaluation.")
        windows = {
            fingerprint(item.spec.get("window") or {}) for item in self.evaluations
        }
        if len(windows) > 1:
            raise StatisticalError("A validation family must share one frozen window.")
        data_ids = {item.spec.get("data", {}).get("fingerprint") for item in self.evaluations}
        if len(data_ids) > 1:
            raise StatisticalError("A validation family must share one frozen dataset.")
        identifiers = [item.candidate.factor_id for item in self.evaluations]
        if len(set(identifiers)) != len(identifiers):
            raise StatisticalError("A validation family cannot contain duplicate factors.")
        for factor_id, _ in self.choices:
            if factor_id not in identifiers:
                raise StatisticalError(f"Choice '{factor_id[:8]}' has no evaluation.")

    @property
    def family_id(self) -> str:
        return fingerprint(
            {
                "schema_version": STATISTICAL_SCHEMA_VERSION,
                "round_index": self.round_index,
                "evaluations": [item.fingerprint() for item in self.evaluations],
                "estimations": [item.fingerprint() for item in self.estimations],
                "feedback": self.feedback.fingerprint() if self.feedback else None,
                "records": fingerprint([dict(row) for row in self.records]),
                "history": [dict(round_) for round_ in self.history],
                "choices": list(self.choices),
                "reward": self.reward_spec.to_dict(),
            }
        )

    @property
    def choice_map(self) -> dict[str, str]:
        return dict(self.choices)

    def observation_for(self, factor_id: str) -> float | None:
        """Stage-1 IC is the only observed statistic, never recomputed here."""
        for evaluation in self.evaluations:
            if evaluation.candidate.factor_id == factor_id:
                value = evaluation.statistics.get("ic")
                if value is None or not math.isfinite(float(value)):
                    return None
                return float(value)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATISTICAL_SCHEMA_VERSION,
            "family_id": self.family_id,
            "round_index": self.round_index,
            "factors": [
                {
                    "factor_id": item.candidate.factor_id,
                    "expression": item.candidate.expression,
                    "fingerprint": item.fingerprint(),
                    "statistics": dict(item.statistics),
                }
                for item in self.evaluations
            ],
            "estimations": [item.to_dict() for item in self.estimations],
            "feedback": self.feedback.to_dict() if self.feedback else None,
            "choices": [list(pair) for pair in self.choices],
            "records_count": len(self.records),
            "history_rounds": len(self.history),
            "reward": self.reward_spec.to_dict(),
        }


def build_family(
    evaluations: Sequence[FactorEvaluation],
    *,
    round_index: int,
    estimations: Sequence[SimulatedEstimation] = (),
    feedback: SimulationFeedback | None = None,
    records: Sequence[Mapping[str, Any]] = (),
    choices: Sequence[tuple[str, str]] = (),
    history: Sequence[Mapping[str, float | None]] = (),
    reward_spec: RewardSpec | None = None,
) -> ValidationFamily:
    """Convenience constructor that freezes every incoming sequence."""
    return ValidationFamily(
        evaluations=tuple(evaluations),
        round_index=round_index,
        estimations=tuple(estimations),
        feedback=feedback,
        records=tuple(dict(row) for row in records),
        choices=tuple((str(key), str(value)) for key, value in choices),
        history=tuple(dict(round_) for round_ in history),
        reward_spec=reward_spec or RewardSpec(),
    )
