"""One shared evaluation object for the whole loop.

Stage 2's GRPO reward, stage 3's proxy training samples and stage 4's test
family must all read the same factor column and the same evaluation values.
``FactorEvaluation`` is that single object: it owns the materialised values,
the descriptive information coefficients and the deterministic backtest
result, plus a spec that records every free parameter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from dynaloop.research_engine.candidates import (
    CompiledFactor,
    EvaluationPolicy,
    FactorCandidate,
)
from dynaloop.research_engine.expressions import FACTOR_SCHEMA_VERSION
from dynaloop.research_engine.frame import FactorFrame, FactorValues
from dynaloop.research_engine.spec import fingerprint, library_versions
from dynaloop.validation_backtesting_engine.services.report import BacktestResult

IC_LABEL = "next_bar_close_to_close_return"


def information_coefficient(
    values: FactorValues,
    frame: FactorFrame,
    *,
    horizon: int = 1,
) -> dict[str, Any]:
    """Pearson IC / Spearman RankIC against the next-bar close-to-close return.

    The forward return is an evaluation label, not a strategy input: it never
    enters the factor expression or the point-in-time signal column. pandas
    owns both correlations; pairwise dropna is the only missing-value rule.
    """
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be a positive integer.")
    if "close" not in frame.columns:
        raise ValueError("IC requires a 'close' column in the frozen frame.")
    close = frame.data["close"]
    forward = close.shift(-horizon) / close - 1.0
    paired = pd.concat(
        [values.to_series().rename("factor"), forward.rename("forward")], axis=1
    ).dropna()
    result: dict[str, Any] = {
        "ic": None,
        "rank_ic": None,
        "observations": int(len(paired)),
        "horizon": horizon,
        "label": IC_LABEL,
        "nan_policy": "pairwise_dropna",
    }
    if len(paired) < 3:
        return result
    if paired["factor"].std(ddof=1) <= 0 or paired["forward"].std(ddof=1) <= 0:
        return result
    ic = float(paired["factor"].corr(paired["forward"], method="pearson"))
    result["ic"] = ic if math.isfinite(ic) else None
    # Spearman's rho is Pearson's r on average ranks. pandas owns both steps.
    factor_rank = paired["factor"].rank(method="average")
    forward_rank = paired["forward"].rank(method="average")
    if factor_rank.std(ddof=1) > 0 and forward_rank.std(ddof=1) > 0:
        rank_ic = float(factor_rank.corr(forward_rank, method="pearson"))
        result["rank_ic"] = rank_ic if math.isfinite(rank_ic) else None
    return result


def build_evaluation_spec(
    *,
    candidate: FactorCandidate,
    policy: EvaluationPolicy,
    frame: FactorFrame,
    values: FactorValues,
    compiled: CompiledFactor,
    statistics: Mapping[str, Any],
    result: BacktestResult,
    start: str | None,
    end: str | None,
    source_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Everything that could change the numbers, with no wall-clock fields."""
    return {
        "schema_version": FACTOR_SCHEMA_VERSION,
        "factor_id": candidate.factor_id,
        "expression": candidate.expression,
        "expression_details": candidate.details,
        "policy": policy.to_dict(),
        "window": {
            "requested_start": start,
            "requested_end": end,
            "realized_start": frame.timestamps[0],
            "realized_end": frame.timestamps[-1],
        },
        "bar_count": len(frame.timestamps),
        "timestamp_col": frame.timestamp_col,
        "data": {
            "columns": list(frame.columns),
            "fingerprint": frame.fingerprint(),
            "source_metadata": dict(source_metadata or {}),
        },
        "compilation": {
            "strategy_class": compiled.strategy_class,
            "strategy_kwargs_fingerprint": fingerprint(compiled.strategy_kwargs),
        },
        "evaluation": {
            "statistics": dict(statistics),
            "values_fingerprint": values.fingerprint(),
        },
        "backtest": {
            "fingerprint": result.fingerprint(),
            "resolved_config": result.resolved_config,
            "engine_spec": result.spec,
            "metrics": result.metrics,
            "warnings": list(result.warnings),
        },
        "library_versions": library_versions(),
    }


@dataclass(frozen=True, slots=True)
class FactorEvaluation:
    """The one representation consumed by every later stage of the loop."""

    candidate: FactorCandidate
    policy: EvaluationPolicy
    values: FactorValues
    compiled: CompiledFactor
    statistics: dict[str, Any]
    backtest: dict[str, Any]
    backtest_fingerprint: str
    spec: dict[str, Any]

    @property
    def metrics(self) -> dict[str, Any]:
        return dict(self.backtest.get("metrics") or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "policy": self.policy.to_dict(),
            "values": self.values.to_dict(),
            "compiled": self.compiled.to_dict(),
            "statistics": dict(self.statistics),
            "backtest": self.backtest,
            "backtest_fingerprint": self.backtest_fingerprint,
            "spec": self.spec,
        }

    def fingerprint(self) -> str:
        return fingerprint(
            {
                "spec": self.spec,
                "values": self.values.to_dict(),
                "statistics": self.statistics,
                "metrics": self.metrics,
                "backtest_fingerprint": self.backtest_fingerprint,
            }
        )
