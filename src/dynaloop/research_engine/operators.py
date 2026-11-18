"""pandas-backed evaluation of the restricted expression language.

qlib evaluates an ``Expression`` through ``load(instrument, start, end, freq)``
and dispatches to each operator's ``_load_internal``. Here the frozen window and
symbol are already resolved by Data, so the equivalent entry point is
``evaluate_expression(node, data, min_periods=...)`` over a ``pd.DataFrame``.
Operator names, arities and rolling semantics mirror ``qlib/data/ops.py``;
pandas owns every rolling / ewm / correlation calculation (no hand-written
recurrences).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from dynaloop.research_engine.expressions import (
    Constant,
    ExpressionEvaluationError,
    Feature,
    Node,
    Operator,
)

OperatorFunction = Callable[[tuple[Node, ...], "EvaluationContext"], pd.Series]


class Operators:
    """Name -> evaluator registry (qlib's ``OpsWrapper`` / ``Operators``)."""

    _registry: dict[str, OperatorFunction] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[OperatorFunction], OperatorFunction]:
        def decorator(function: OperatorFunction) -> OperatorFunction:
            cls._registry[name] = function
            return function

        return decorator

    @classmethod
    def get_operator(cls, name: str) -> OperatorFunction:
        try:
            return cls._registry[name]
        except KeyError as exc:
            raise ExpressionEvaluationError(f"Operator {name!r} has no evaluator.") from exc

    @classmethod
    def names(cls) -> tuple[str, ...]:
        return tuple(sorted(cls._registry))


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Frozen columns plus the warm-up policy (qlib's min_periods=1 default)."""

    data: pd.DataFrame
    min_periods: int | None = 1

    def evaluate(self, node: Node) -> pd.Series:
        return evaluate_node(node, self)

    def window(self, length: int) -> int:
        if self.min_periods is None:
            return length
        return max(1, min(int(self.min_periods), length))

    @property
    def index(self) -> pd.Index:
        return self.data.index


def _finite(series: pd.Series) -> pd.Series:
    """Infinity is not a factor value; keep NaN as the explicit missing marker."""
    return pd.Series(
        np.asarray(series, dtype=float).copy(), index=series.index, dtype=float
    ).replace([np.inf, -np.inf], np.nan)


def _unary(series: pd.Series, function: Callable[[np.ndarray], np.ndarray]) -> pd.Series:
    return pd.Series(function(series.to_numpy(dtype=float)), index=series.index)


def evaluate_node(node: Node, context: EvaluationContext) -> pd.Series:
    if isinstance(node, Feature):
        if node.name not in context.data.columns:
            raise ExpressionEvaluationError(
                f"Column ${node.name} is not available in this dataset. "
                f"Available: {', '.join(map(str, context.data.columns))}."
            )
        return _finite(context.data[node.name])
    if isinstance(node, Constant):
        return pd.Series(float(node.value), index=context.index, dtype=float)
    if isinstance(node, Operator):
        return _finite(Operators.get_operator(node.name)(node.args, context))
    raise ExpressionEvaluationError(f"Unsupported expression node: {node!r}.")


def evaluate_expression(
    node: Node,
    data: pd.DataFrame,
    *,
    min_periods: int | None = 1,
) -> pd.Series:
    """Evaluate one expression over the frozen frame (qlib ``Expression.load``)."""
    context = EvaluationContext(data=data, min_periods=min_periods)
    series = context.evaluate(node)
    series.name = str(node)
    return series


# --------------------------------------------------------------------------
# Element-wise operators (qlib NpElemOperator)
# --------------------------------------------------------------------------


@Operators.register("Abs")
def _abs(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return ctx.evaluate(args[0]).abs()


@Operators.register("Sign")
def _sign(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return _unary(ctx.evaluate(args[0]), np.sign)


@Operators.register("Log")
def _log(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    series = ctx.evaluate(args[0])
    return _unary(series.where(series > 0), np.log)


@Operators.register("Not")
def _not(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    # Non-zero/non-missing is True; missing is False, as a boolean mask.
    return (ctx.evaluate(args[0]).fillna(0.0) == 0).astype(float)


# --------------------------------------------------------------------------
# Pair-wise operators (qlib NpPairOperator)
# --------------------------------------------------------------------------


def _pair(args: tuple[Node, ...], ctx: EvaluationContext) -> tuple[pd.Series, pd.Series]:
    return ctx.evaluate(args[0]), ctx.evaluate(args[1])


@Operators.register("Add")
def _add(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return left + right


@Operators.register("Sub")
def _sub(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return left - right


@Operators.register("Mul")
def _mul(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return left * right


@Operators.register("Div")
def _div(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return left / right.replace(0.0, np.nan)


@Operators.register("Power")
def _power(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return left.pow(right)


@Operators.register("Greater")
def _greater(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return _unary_pair(left, right, np.maximum)


@Operators.register("Less")
def _less(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return _unary_pair(left, right, np.minimum)


def _unary_pair(
    left: pd.Series,
    right: pd.Series,
    function: Callable[[np.ndarray, np.ndarray], np.ndarray],
) -> pd.Series:
    return pd.Series(
        function(left.to_numpy(dtype=float), right.to_numpy(dtype=float)),
        index=left.index,
    )


def _comparison(
    args: tuple[Node, ...],
    ctx: EvaluationContext,
    operation: Callable[[pd.Series, pd.Series], pd.Series],
) -> pd.Series:
    left, right = _pair(args, ctx)
    return operation(left, right).astype(float)


@Operators.register("Gt")
def _gt(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return _comparison(args, ctx, lambda a, b: a > b)


@Operators.register("Ge")
def _ge(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return _comparison(args, ctx, lambda a, b: a >= b)


@Operators.register("Lt")
def _lt(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return _comparison(args, ctx, lambda a, b: a < b)


@Operators.register("Le")
def _le(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return _comparison(args, ctx, lambda a, b: a <= b)


@Operators.register("Eq")
def _eq(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return _comparison(args, ctx, lambda a, b: a == b)


@Operators.register("Ne")
def _ne(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return _comparison(args, ctx, lambda a, b: a != b)


@Operators.register("And")
def _and(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return ((left.fillna(0.0) != 0) & (right.fillna(0.0) != 0)).astype(float)


@Operators.register("Or")
def _or(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = _pair(args, ctx)
    return ((left.fillna(0.0) != 0) | (right.fillna(0.0) != 0)).astype(float)


@Operators.register("If")
def _if(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    condition = ctx.evaluate(args[0]).fillna(0.0) != 0
    return ctx.evaluate(args[1]).where(condition, ctx.evaluate(args[2]))


# --------------------------------------------------------------------------
# Time-series operators (qlib Rolling / PairRolling)
# --------------------------------------------------------------------------


@Operators.register("Ref")
def _ref(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    return ctx.evaluate(args[0]).shift(int(args[1].value))


@Operators.register("Delta")
def _delta(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    series = ctx.evaluate(args[0])
    return series - series.shift(int(args[1].value))


def _rolling(args: tuple[Node, ...], ctx: EvaluationContext) -> tuple[pd.Series, int, int]:
    series = ctx.evaluate(args[0])
    length = int(args[1].value)
    return series, length, ctx.window(length)


def _simple_rolling(name: str, method: str):
    def evaluator(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
        series, length, minimum = _rolling(args, ctx)
        return getattr(series.rolling(length, min_periods=minimum), method)()

    evaluator.__name__ = f"_{name.lower()}"
    evaluator.__doc__ = f"qlib {name}: pandas rolling {method} with explicit min_periods."
    return evaluator


for _name, _method in (
    ("Mean", "mean"),
    ("Sum", "sum"),
    ("Std", "std"),
    ("Var", "var"),
    ("Max", "max"),
    ("Min", "min"),
    ("Med", "median"),
    ("Count", "count"),
):
    Operators.register(_name)(_simple_rolling(_name, _method))


@Operators.register("Rank")
def _rank(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    """qlib Rank: rolling percentile rank of the current value (pct=True)."""
    series, length, minimum = _rolling(args, ctx)

    def percentile(window: np.ndarray) -> float:
        ranked = pd.Series(window).rank(pct=True, method="average")
        return float(ranked.iloc[-1])

    return series.rolling(length, min_periods=minimum).apply(percentile, raw=True)


@Operators.register("EMA")
def _ema(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    series = ctx.evaluate(args[0])
    value = float(args[1].value)
    if value == 0:
        return series.expanding(min_periods=ctx.window(len(series))).mean()
    if 0 < value < 1:
        return series.ewm(alpha=value, min_periods=ctx.window(len(series)), adjust=True).mean()
    return series.ewm(span=value, min_periods=ctx.window(int(value)), adjust=True).mean()


@Operators.register("WMA")
def _wma(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    """Linearly weighted mean; NaN observations are excluded with their weights."""
    series, length, minimum = _rolling(args, ctx)

    def weighted(window: np.ndarray) -> float:
        values = np.asarray(window, dtype=float)
        weights = np.arange(1, len(values) + 1, dtype=float)
        observed = ~np.isnan(values)
        if not observed.any():
            return float("nan")
        return float(np.average(values[observed], weights=weights[observed]))

    return series.rolling(length, min_periods=minimum).apply(weighted, raw=True)


@Operators.register("Corr")
def _corr(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = ctx.evaluate(args[0]), ctx.evaluate(args[1])
    length = int(args[2].value)
    return left.rolling(length, min_periods=ctx.window(length)).corr(right)


@Operators.register("Cov")
def _cov(args: tuple[Node, ...], ctx: EvaluationContext) -> pd.Series:
    left, right = ctx.evaluate(args[0]), ctx.evaluate(args[1])
    length = int(args[2].value)
    return left.rolling(length, min_periods=ctx.window(length)).cov(right)


def is_finite_number(value: object) -> bool:
    """Small shared predicate used when serialising factor values."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
