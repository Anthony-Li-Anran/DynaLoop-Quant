"""Reward and group-relative advantages for the research loop.

Reward is a *training signal*, never a system success criterion (system contract
§1.4). It is read only from ``FactorEvaluation.statistics`` — the same object
stages 3/4 consume — and never from backtest P&L metrics. Group advantages follow
TRL's ``GRPOTrainer._generate_and_score_completions``:

    advantages = (rewards - mean_grouped_rewards) / (std_grouped_rewards + 1e-4)

torch's ``.std`` is the unbiased estimator, so numpy uses ``ddof=1``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from dynaloop.research_engine.evaluation import FactorEvaluation

REWARD_LABELS = ("abs_rank_ic", "abs_ic", "rank_ic", "ic")


class RewardError(ValueError):
    """Reward inputs are invalid or outside the declared reward contract."""


@dataclass(frozen=True, slots=True)
class RewardSpec:
    """The full reward definition; ``uses_pnl`` is deliberately always false."""

    label: str = "abs_rank_ic"
    missing_value: float = 0.0
    scale_rewards: bool = True
    epsilon: float = 1e-4

    def __post_init__(self) -> None:
        if self.label not in REWARD_LABELS:
            raise RewardError(f"label must be one of {REWARD_LABELS}.")
        if not math.isfinite(float(self.missing_value)):
            raise RewardError("missing_value must be finite.")
        if not math.isfinite(float(self.epsilon)) or self.epsilon <= 0:
            raise RewardError("epsilon must be a finite positive number.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "missing_value": self.missing_value,
            "scale_rewards": self.scale_rewards,
            "epsilon": self.epsilon,
            "source": "FactorEvaluation.statistics",
            "uses_pnl": False,
        }


def factor_reward(
    evaluation: FactorEvaluation,
    spec: RewardSpec | None = None,
) -> float:
    """Read one descriptive statistic; no fallback into backtest metrics."""
    resolved = spec or RewardSpec()
    statistics = evaluation.statistics
    raw = statistics.get("rank_ic" if "rank_ic" in resolved.label else "ic")
    if raw is None:
        return resolved.missing_value
    value = float(raw)
    if not math.isfinite(value):
        return resolved.missing_value
    return abs(value) if resolved.label.startswith("abs_") else value


def group_advantages(
    rewards: Sequence[float],
    *,
    scale_rewards: bool = True,
    epsilon: float = 1e-4,
) -> tuple[float, ...]:
    """TRL's group-relative normalisation over the whole candidate group."""
    values = np.asarray(list(rewards), dtype=float)
    if values.size == 0:
        return ()
    if not np.all(np.isfinite(values)):
        raise RewardError("Rewards must all be finite.")
    centred = values - values.mean()
    if scale_rewards and values.size > 1:
        spread = float(values.std(ddof=1))
        centred = centred / (spread + epsilon)
    return tuple(float(value) for value in centred)
