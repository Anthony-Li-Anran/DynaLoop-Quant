"""Factor candidates and their compiled strategy form.

The original architecture discovers candidate factors ``f1..fN``. A candidate
is identified by its canonical qlib-style expression; the compiled form is a
``BaseStrategy`` class path + JSON-safe kwargs, exactly the shape the existing
``build_strategy`` / ``run_saved_config`` contract already consumes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from dynaloop.research_engine.expressions import (
    FACTOR_SCHEMA_VERSION,
    FactorError,
    expression_details,
    normalize_expression,
    parse_expression,
)
from dynaloop.research_engine.frame import FactorValues
from dynaloop.research_engine.spec import fingerprint

FACTOR_STRATEGY_CLASS = "dynaloop.research_engine.strategies.FactorSignalStrategy"


@dataclass(frozen=True, slots=True)
class EvaluationPolicy:
    """Everything that changes a factor's numbers, recorded in every spec.

    ``min_periods`` follows qlib's rolling default of 1; ``None`` means a full
    window is required. ``nan_policy`` is deliberately single-valued: no fill,
    no interpolation, no forward-fill. NaN stays NaN (JSON ``null``).
    """

    min_periods: int | None = 1
    nan_policy: str = "propagate"
    adjust: str = "qfq"
    frequency: str = "1d"
    threshold: float = 0.0
    allocation: float = 0.95
    rule: str = "long_flat"
    ic_horizon: int = 1

    def __post_init__(self) -> None:
        if self.min_periods is not None and (not isinstance(self.min_periods, int) or self.min_periods < 1):
            raise FactorError("min_periods must be None or a positive integer.")
        if self.nan_policy != "propagate":
            raise FactorError("Only the 'propagate' NaN policy is defined.")
        if self.rule not in ("long_flat", "long_short"):
            raise FactorError("rule must be 'long_flat' or 'long_short'.")
        if not 0 < self.allocation <= 1:
            raise FactorError("allocation must be in (0, 1].")
        if not isinstance(self.threshold, (int, float)) or not math.isfinite(float(self.threshold)):
            raise FactorError("threshold must be finite.")
        if not isinstance(self.ic_horizon, int) or self.ic_horizon < 1:
            raise FactorError("ic_horizon must be a positive integer.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_periods": self.min_periods,
            "nan_policy": self.nan_policy,
            "adjust": self.adjust,
            "frequency": self.frequency,
            "threshold": self.threshold,
            "allocation": self.allocation,
            "rule": self.rule,
            "ic_horizon": self.ic_horizon,
        }


@dataclass(frozen=True, slots=True)
class FactorCandidate:
    """One discovered factor: canonical expression + stable identity."""

    factor_id: str
    expression: str
    raw_expression: str
    details: dict[str, Any]

    @classmethod
    def from_expression(cls, text: str) -> "FactorCandidate":
        expression = normalize_expression(text)
        details = expression_details(parse_expression(expression))
        identity = fingerprint(
            {"expression": expression, "schema_version": FACTOR_SCHEMA_VERSION}
        )
        return cls(
            factor_id=identity,
            expression=expression,
            raw_expression=str(text),
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "expression": self.expression,
            "raw_expression": self.raw_expression,
            **self.details,
        }


@dataclass(frozen=True, slots=True)
class CompiledFactor:
    """The strategy configuration the backtest engine can resolve directly."""

    factor_id: str
    strategy_class: str
    strategy_kwargs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "strategy_class": self.strategy_class,
            "strategy_kwargs": dict(self.strategy_kwargs),
        }


def compile_factor(
    candidate: FactorCandidate,
    values: FactorValues,
    *,
    policy: EvaluationPolicy | Mapping[str, Any] | None = None,
    symbol: str | None = None,
) -> CompiledFactor:
    """Materialise the factor column into a ``BaseStrategy`` configuration."""
    resolved = policy if isinstance(policy, EvaluationPolicy) else EvaluationPolicy(**dict(policy or {}))
    if values.timestamps and len(values.timestamps) != len(values.values):
        raise FactorError("Factor values and timestamps have different lengths.")
    kwargs: dict[str, Any] = {
        "signals": values.signals(),
        "threshold": resolved.threshold,
        "allocation": resolved.allocation,
        "rule": resolved.rule,
        "symbol": symbol,
    }
    return CompiledFactor(
        factor_id=candidate.factor_id,
        strategy_class=FACTOR_STRATEGY_CLASS,
        strategy_kwargs=kwargs,
    )
