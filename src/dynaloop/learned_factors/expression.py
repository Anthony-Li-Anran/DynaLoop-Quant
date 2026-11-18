"""A small, local expression engine with Qlib DataLoader semantics.

The project's existing ``research_engine.expressions`` engine is intentionally
look-ahead safe: it rejects negative ``Ref`` and exposes a fixed operator set.
Qlib's data loader uses a different contract (rolling with ``min_periods=1``,
future ``Ref`` only for labels, regression operators, etc.). Rather than weaken
the production engine, this module implements that contract locally.

Every operator mirrors ``qlib/data/ops.py`` (and ``qlib/data/_libs/rolling.pyx``
for Slope / Rsquare / Resi). Nothing here imports qlib.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Callable

import numpy as np
import pandas as pd

_FIELD = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")

FUNCTIONS = frozenset(
    {
        "Ref", "Mean", "Sum", "Std", "Var", "Max", "Min", "Quantile", "Rank",
        "IdxMax", "IdxMin", "Slope", "Rsquare", "Resi", "Corr",
        "Greater", "Less", "Log", "Abs", "Sign",
    }
)

_BINARY: dict[type, Callable] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_COMPARE: dict[type, Callable] = {
    ast.Gt: operator.gt,
    ast.Lt: operator.lt,
    ast.GtE: operator.ge,
    ast.LtE: operator.le,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}


class ExpressionError(ValueError):
    """Raised for unsupported syntax or an unknown base field."""


def _rewrite(text: str) -> str:
    return _FIELD.sub(lambda m: f'F("{m.group(1)}")', text)


def parse(text: str) -> ast.AST:
    """Parse and whitelist-check one Qlib-style expression."""
    try:
        tree = ast.parse(_rewrite(text), mode="eval").body
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression {text!r}: {exc}") from exc
    _validate(tree)
    return tree


def _validate(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError("only numeric literals are allowed")
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("only plain function calls are allowed")
        name = node.func.id
        if name == "F":
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
                raise ExpressionError("F() requires one literal field name")
            return
        if name not in FUNCTIONS:
            raise ExpressionError(f"unsupported operator: {name}")
        for arg in node.args:
            _validate(arg)
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        _validate(node.left)
        _validate(node.right)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        _validate(node.operand)
        return
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
        _validate(node.left)
        _validate(node.comparators[0])
        return
    raise ExpressionError(f"unsupported syntax: {ast.dump(node)[:80]}")


def _literal(node: ast.AST) -> float:
    """Numeric literal, including a leading sign (``Ref($close, -2)``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_literal(node.operand)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return _literal(node.operand)
    raise ExpressionError("a literal numeric parameter is required")


def _rolling(series: pd.Series, length: int, method: str) -> pd.Series:
    # Qlib Rolling._load_internal: rolling(N, min_periods=1).
    return getattr(series.rolling(length, min_periods=1), method)()


def _regression(series: pd.Series, length: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Vectorised equivalent of qlib's Cython rolling regression operators.

    x is the position inside the window (1..N); only non-NaN observations
    participate. Resi uses the newest observation at x=N.
    """
    y = series.to_numpy(dtype=float)
    padded = np.concatenate([np.full(length - 1, np.nan), y])
    windows = np.lib.stride_tricks.sliding_window_view(padded, length)[: len(y)]
    mask = ~np.isnan(windows)
    count = mask.sum(axis=1)
    values = np.where(mask, windows, 0.0)
    x = np.arange(1, length + 1, dtype=float)[None, :]
    xm = np.where(mask, x, 0.0)
    sx = xm.sum(axis=1)
    sy = values.sum(axis=1)
    sxx = (xm * xm).sum(axis=1)
    syy = (values * values).sum(axis=1)
    sxy = (xm * values).sum(axis=1)
    den_x = count * sxx - sx * sx
    den_y = count * syy - sy * sy
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (count * sxy - sx * sy) / den_x
        intercept = (sy - slope * sx) / count
        rsquare = ((count * sxy - sx * sy) ** 2) / (den_x * den_y)
        residual = values[:, -1] - (slope * length + intercept)
    # qlib's Cython Slope/Resi only need a valid x-denominator: on a flat
    # price window they return 0, not NaN. Only Rsquare needs the y-variance.
    bad_x = (
        (count < 2)
        | ~np.isfinite(den_x)
        | (den_x <= 1e-12)
        | np.isnan(windows[:, -1])
    )
    bad_r2 = bad_x | ~np.isfinite(den_y) | (den_y <= 1e-12)
    slope[bad_x] = np.nan
    residual[bad_x] = np.nan
    rsquare[bad_r2] = np.nan
    # qlib/data/ops.py Rsquare._load_internal additionally nulls out windows
    # whose rolling standard deviation is numerically flat. This applies to
    # Rsquare only; Slope and Resi keep their Cython behaviour.
    flat = np.isclose(
        series.rolling(length, min_periods=1).std().to_numpy(dtype=float),
        0.0,
        atol=2e-05,
    )
    rsquare[flat] = np.nan
    index = series.index
    return (
        pd.Series(slope, index=index),
        pd.Series(rsquare, index=index),
        pd.Series(residual, index=index),
    )


class ExpressionEvaluator:
    """Evaluate Qlib-style expressions on one instrument's base-field frame.

    Results are memoised by expression text, so shared sub-expressions (e.g.
    ``Ref($close, 1)``, ``Log($volume+1)``) are computed once per instrument.
    """

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self._series_cache: dict[str, pd.Series] = {}
        self._regression_cache: dict[tuple[str, int], tuple[pd.Series, ...]] = {}

    def evaluate(self, text: str) -> pd.Series:
        cached = self._series_cache.get(text)
        if cached is not None:
            return cached
        result = self._eval(parse(text))
        result = pd.Series(
            np.asarray(result, dtype=float), index=self.frame.index, dtype=float
        ).replace([np.inf, -np.inf], np.nan)
        self._series_cache[text] = result
        return result

    def _constant(self, value: float) -> pd.Series:
        return pd.Series(float(value), index=self.frame.index, dtype=float)

    def _eval(self, node: ast.AST) -> pd.Series:
        if isinstance(node, ast.Constant):
            return self._constant(node.value)
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.BinOp):
            left, right = self._eval(node.left), self._eval(node.right)
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                return pd.Series(
                    _BINARY[type(node.op)](left.to_numpy(), right.to_numpy()),
                    index=self.frame.index,
                )
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.Compare):
            left, right = self._eval(node.left), self._eval(node.comparators[0])
            return pd.Series(
                _COMPARE[type(node.ops[0])](left.to_numpy(), right.to_numpy()).astype(float),
                index=self.frame.index,
            )
        raise ExpressionError(f"unsupported node: {type(node).__name__}")

    def _arg_text(self, node: ast.AST) -> str:
        return ast.unparse(node).replace('"', "'")

    def _call(self, node: ast.Call) -> pd.Series:
        name = node.func.id
        if name == "F":
            field = node.args[0].value
            if field not in self.frame.columns:
                raise ExpressionError(f"base field ${field} is unavailable")
            return self.frame[field].astype(float)

        args = node.args
        if name == "Ref":
            return self._eval(args[0]).shift(int(_literal(args[1])))
        if name in ("Greater", "Less"):
            left, right = self._eval(args[0]), self._eval(args[1])
            fn = np.maximum if name == "Greater" else np.minimum
            return pd.Series(fn(left.to_numpy(), right.to_numpy()), index=self.frame.index)
        if name in ("Log", "Abs", "Sign"):
            fn = {"Log": np.log, "Abs": np.abs, "Sign": np.sign}[name]
            with np.errstate(divide="ignore", invalid="ignore"):
                return pd.Series(fn(self._eval(args[0]).to_numpy()), index=self.frame.index)
        if name == "Corr":
            left, right = self._eval(args[0]), self._eval(args[1])
            length = int(_literal(args[2]))
            out = left.rolling(length, min_periods=1).corr(right)
            flat = (np.isclose(left.rolling(length, min_periods=1).std(), 0, atol=2e-05)
                    | np.isclose(right.rolling(length, min_periods=1).std(), 0, atol=2e-05))
            out[flat] = np.nan
            return out
        if name == "Quantile":
            length, q = int(_literal(args[1])), float(_literal(args[2]))
            return self._eval(args[0]).rolling(length, min_periods=1).quantile(q)
        if name == "Rank":
            length = int(_literal(args[1]))
            return self._eval(args[0]).rolling(length, min_periods=1).rank(pct=True)
        if name in ("IdxMax", "IdxMin"):
            length = int(_literal(args[1]))
            fn = np.argmax if name == "IdxMax" else np.argmin
            return self._eval(args[0]).rolling(length, min_periods=1).apply(
                lambda w: float(fn(w) + 1), raw=True
            )
        if name in ("Slope", "Rsquare", "Resi"):
            length = int(_literal(args[1]))
            key = (self._arg_text(args[0]), length)
            triple = self._regression_cache.get(key)
            if triple is None:
                triple = _regression(self._eval(args[0]), length)
                self._regression_cache[key] = triple
            return triple[{"Slope": 0, "Rsquare": 1, "Resi": 2}[name]]
        if name in ("Mean", "Sum", "Std", "Var", "Max", "Min"):
            length = int(_literal(args[1]))
            method = {"Mean": "mean", "Sum": "sum", "Std": "std",
                      "Var": "var", "Max": "max", "Min": "min"}[name]
            return _rolling(self._eval(args[0]), length, method)
        raise ExpressionError(f"unsupported operator: {name}")


def assert_no_future_reference(expressions: dict[str, str]) -> None:
    """Feature definitions must never read a future bar; labels may."""
    for name, text in expressions.items():
        tree = parse(text)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Ref" and len(node.args) == 2):
                continue
            try:
                offset = _literal(node.args[1])
            except ExpressionError:
                continue
            if offset < 0:
                raise ExpressionError(f"feature {name} reads a future bar: {text}")
