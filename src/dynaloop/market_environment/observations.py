"""Read-only Wake observations derived from stage 1 ``FactorEvaluation``.

Stage 3 never re-runs the deterministic backtest: Wake's verdict is consumed
exactly as produced by ``FactorResearch`` / ``backtest_from_records``. All
fields here are copied, never mutated, so the frozen anchor (data window,
evaluation policy, resolved config, spec and fingerprint) stays read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from dynaloop.research_engine import FactorCandidate, FactorEvaluation
from dynaloop.training_engine import RewardSpec, factor_reward


def factor_group_key(candidate: FactorCandidate) -> str:
    """Structural group of a factor, shared by Wake samples and Sleep estimates.

    Two expressions with the same source-declared features and the same qlib
    operators belong to one group. The proxy therefore generalises across
    unseen expressions instead of memorising full expression strings.
    """
    details = candidate.details or {}
    features = ",".join(str(item) for item in (details.get("features") or ()))
    operators = ",".join(str(item) for item in (details.get("operators") or ()))
    return f"features={features}|operators={operators}"


@dataclass(frozen=True, slots=True)
class FrozenWindow:
    """The frozen data window, copied from one evaluation spec."""

    symbol: str
    requested_start: str | None
    requested_end: str | None
    realized_start: str
    realized_end: str
    bar_count: int
    data_fingerprint: str

    @classmethod
    def from_evaluation(cls, evaluation: FactorEvaluation) -> "FrozenWindow":
        window = dict(evaluation.spec.get("window") or {})
        data = dict(evaluation.spec.get("data") or {})
        symbol = str((evaluation.compiled.strategy_kwargs or {}).get("symbol") or "")
        return cls(
            symbol=symbol,
            requested_start=window.get("requested_start"),
            requested_end=window.get("requested_end"),
            realized_start=str(window.get("realized_start") or ""),
            realized_end=str(window.get("realized_end") or ""),
            bar_count=int(evaluation.spec.get("bar_count") or 0),
            data_fingerprint=str(data.get("fingerprint") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "realized_start": self.realized_start,
            "realized_end": self.realized_end,
            "bar_count": self.bar_count,
            "data_fingerprint": self.data_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class WakeObservation:
    """One candidate's deterministic real-world verdict."""

    factor_id: str
    expression: str
    group_key: str
    reward: float
    evaluation_fingerprint: str
    window: FrozenWindow

    @classmethod
    def from_evaluation(
        cls,
        evaluation: FactorEvaluation,
        reward_spec: RewardSpec | None = None,
    ) -> "WakeObservation":
        spec = reward_spec or RewardSpec()
        return cls(
            factor_id=evaluation.candidate.factor_id,
            expression=evaluation.candidate.expression,
            group_key=factor_group_key(evaluation.candidate),
            reward=factor_reward(evaluation, spec),
            evaluation_fingerprint=evaluation.fingerprint(),
            window=FrozenWindow.from_evaluation(evaluation),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "expression": self.expression,
            "group_key": self.group_key,
            "reward": self.reward,
            "evaluation_fingerprint": self.evaluation_fingerprint,
            "window": self.window.to_dict(),
        }


def wake_observations(
    evaluations: Iterable[FactorEvaluation],
    reward_spec: RewardSpec | None = None,
) -> tuple[WakeObservation, ...]:
    """Convert a test family of evaluations into read-only Wake samples."""
    spec = reward_spec or RewardSpec()
    return tuple(WakeObservation.from_evaluation(item, spec) for item in evaluations)


def require_same_window(window: FrozenWindow, observations: Sequence[WakeObservation]) -> FrozenWindow:
    """Reject mixing evaluations from different frozen windows."""
    for observation in observations:
        if observation.window != window:
            raise ValueError("All Wake observations must share one frozen window.")
    return window


__all__ = [
    "FrozenWindow",
    "WakeObservation",
    "factor_group_key",
    "require_same_window",
    "wake_observations",
]
