"""Restricted factor expression language with a qlib-compatible surface.

Operator names and the ``$feature`` notation follow ``microsoft/qlib``'s
``qlib/data/ops.py`` / ``qlib/data/base.py``; infix operators map to the same
classes as ``Expression.__add__`` / ``__truediv__`` / ``__gt__``. Parsing
follows qlib's current ``qlib/data/expression_parser.py``: an ``ast``
whitelist, never ``eval``. qlib rewrites ``$close`` with ``parse_field`` before
parsing; here a quote-aware rewrite emits ``Feature("close")`` instead.

Deliberate difference from qlib: negative ``Ref`` / forward-looking operators
are rejected, because a factor value at bar t may only depend on bars <= t.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any

FACTOR_SCHEMA_VERSION = 1
MAX_EXPRESSION_CHARS = 4096
MAX_NODES = 512

_FEATURE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_BINARY = {
    ast.Add: "Add",
    ast.Sub: "Sub",
    ast.Mult: "Mul",
    ast.Div: "Div",
    ast.Pow: "Power",
    ast.BitAnd: "And",
    ast.BitOr: "Or",
}
_COMPARE = {
    ast.Gt: "Gt",
    ast.GtE: "Ge",
    ast.Lt: "Lt",
    ast.LtE: "Le",
    ast.Eq: "Eq",
    ast.NotEq: "Ne",
}

# Operator name -> (min arity, max arity). Names are qlib's OpsList names.
OPERATOR_ARITY: dict[str, tuple[int, int]] = {
    "Abs": (1, 1),
    "Sign": (1, 1),
    "Log": (1, 1),
    "Not": (1, 1),
    "Add": (2, 2),
    "Sub": (2, 2),
    "Mul": (2, 2),
    "Div": (2, 2),
    "Power": (2, 2),
    "Greater": (2, 2),
    "Less": (2, 2),
    "Gt": (2, 2),
    "Ge": (2, 2),
    "Lt": (2, 2),
    "Le": (2, 2),
    "Eq": (2, 2),
    "Ne": (2, 2),
    "And": (2, 2),
    "Or": (2, 2),
    "If": (3, 3),
    "Ref": (2, 2),
    "Mean": (2, 2),
    "Sum": (2, 2),
    "Std": (2, 2),
    "Var": (2, 2),
    "Max": (2, 2),
    "Min": (2, 2),
    "Med": (2, 2),
    "Count": (2, 2),
    "Rank": (2, 2),
    "Delta": (2, 2),
    "EMA": (2, 2),
    "WMA": (2, 2),
    "Corr": (3, 3),
    "Cov": (3, 3),
}

ELEMENTWISE = frozenset({"Abs", "Sign", "Log", "Not"})
PAIRWISE = frozenset(
    {"Add", "Sub", "Mul", "Div", "Power", "Greater", "Less", "Gt", "Ge",
     "Lt", "Le", "Eq", "Ne", "And", "Or"}
)
WINDOW_OPERATORS = frozenset(
    {"Mean", "Sum", "Std", "Var", "Max", "Min", "Med", "Count", "Rank", "EMA", "WMA"}
)
SHIFT_OPERATORS = frozenset({"Ref", "Delta"})
PAIR_WINDOW_OPERATORS = frozenset({"Corr", "Cov"})

NUMERIC_PARAMETER_POSITIONS: dict[str, tuple[int, ...]] = {
    **{name: (1,) for name in WINDOW_OPERATORS | SHIFT_OPERATORS},
    **{name: (2,) for name in PAIR_WINDOW_OPERATORS},
}


class FactorError(ValueError):
    """Base error for the factor language."""


class ExpressionSyntaxError(FactorError):
    """The expression leaves the restricted language (qlib's naming)."""


class ExpressionEvaluationError(FactorError):
    """The expression is valid but cannot be evaluated on these records."""


@dataclass(frozen=True, slots=True)
class Feature:
    """A raw column. ``__str__`` matches qlib's ``Feature.__str__``."""

    name: str

    def __str__(self) -> str:
        return "$" + self.name


@dataclass(frozen=True, slots=True)
class Constant:
    """A numeric literal (qlib allows numeric operands alongside Expressions)."""

    value: float | int

    def __str__(self) -> str:
        return repr(self.value)


@dataclass(frozen=True, slots=True)
class Operator:
    """A registered qlib operator applied to already-parsed nodes."""

    name: str
    args: tuple["Node", ...]

    def __str__(self) -> str:
        return f"{self.name}({','.join(str(arg) for arg in self.args)})"


Node = Feature | Constant | Operator


def _rewrite_fields(source: str) -> str:
    """Turn ``$close`` into ``Feature("close")`` without touching literals."""
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote is not None:
            output.append(char)
            if char == "\\" and index + 1 < len(source):
                output.append(source[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            output.append(char)
            index += 1
            continue
        if char == "$":
            match = _FEATURE.match(source, index)
            if match is None:
                raise ExpressionSyntaxError(f"Invalid field reference at position {index}.")
            output.append(f'Feature("{match.group(1)}")')
            index = match.end()
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _validate_parameters(name: str, args: tuple[Node, ...]) -> None:
    positions = NUMERIC_PARAMETER_POSITIONS.get(name, ())
    for position in positions:
        argument = args[position]
        if not isinstance(argument, Constant):
            raise ExpressionSyntaxError(f"{name} requires a literal window parameter.")
        raw = argument.value
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise ExpressionSyntaxError(f"{name} requires a finite numeric window parameter.")
        value = float(raw)
        if name == "EMA":
            # qlib: 0 means expanding, 0 < N < 1 means ewm(alpha=N).
            if not (value == 0 or 0 < value < 1 or (value >= 1 and value.is_integer())):
                raise ExpressionSyntaxError("EMA window must be 0, in (0, 1), or a positive integer.")
        elif name == "Ref":
            if value < 0 or not value.is_integer():
                raise ExpressionSyntaxError(
                    "Ref requires a non-negative integer N; negative N would read future bars."
                )
        elif name in SHIFT_OPERATORS | WINDOW_OPERATORS | PAIR_WINDOW_OPERATORS:
            if value < 1 or not value.is_integer():
                raise ExpressionSyntaxError(f"{name} requires a positive integer window.")


def _build(node: ast.AST) -> Node:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionSyntaxError("Only numeric literals are allowed outside Feature(...).")
        return Constant(node.value)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "Operators"
        ):
            name = node.func.attr
        else:
            raise ExpressionSyntaxError("Only registered operators may be called.")
        if node.keywords:
            raise ExpressionSyntaxError("Keyword arguments are not supported.")
        if name == "Feature":
            if (
                len(node.args) != 1
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
                or not _FIELD_NAME.fullmatch(node.args[0].value)
            ):
                raise ExpressionSyntaxError("Feature(...) requires one column name.")
            return Feature(node.args[0].value)
        if name not in OPERATOR_ARITY:
            raise ExpressionSyntaxError(f"Unknown operator: {name}.")
        low, high = OPERATOR_ARITY[name]
        if not low <= len(node.args) <= high:
            raise ExpressionSyntaxError(f"{name} expects {low}..{high} arguments.")
        args = tuple(_build(argument) for argument in node.args)
        _validate_parameters(name, args)
        return Operator(name, args)
    if isinstance(node, ast.BinOp):
        name = _BINARY.get(type(node.op))
        if name is None:
            raise ExpressionSyntaxError(f"Unsupported operator: {type(node.op).__name__}.")
        return Operator(name, (_build(node.left), _build(node.right)))
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return Operator("Mul", (Constant(-1), _build(node.operand)))
        if isinstance(node.op, ast.UAdd):
            return _build(node.operand)
        raise ExpressionSyntaxError("Only unary +/- are supported.")
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ExpressionSyntaxError("Chained comparisons are not supported.")
        name = _COMPARE.get(type(node.ops[0]))
        if name is None:
            raise ExpressionSyntaxError("Unsupported comparison.")
        return Operator(name, (_build(node.left), _build(node.comparators[0])))
    raise ExpressionSyntaxError(f"Unsupported syntax: {type(node).__name__}.")


def _count_nodes(node: Node) -> int:
    if isinstance(node, Operator):
        return 1 + sum(_count_nodes(arg) for arg in node.args)
    return 1


def parse_expression(text: str | Node) -> Node:
    """Parse a qlib-style expression into a validated, hashable node tree."""
    if isinstance(text, (Feature, Constant, Operator)):
        return text
    if not isinstance(text, str) or not text.strip():
        raise ExpressionSyntaxError("A factor expression must be a non-empty string.")
    if len(text) > MAX_EXPRESSION_CHARS:
        raise ExpressionSyntaxError("Expression is too long.")
    rewritten = _rewrite_fields(text.strip())
    try:
        tree = ast.parse(rewritten, mode="eval")
    except SyntaxError as exc:
        raise ExpressionSyntaxError(f"Invalid factor expression syntax: {text!r}.") from exc
    node = _build(tree.body)
    if isinstance(node, Constant):
        raise ExpressionSyntaxError("A factor expression must reference at least one feature.")
    if _count_nodes(node) > MAX_NODES:
        raise ExpressionSyntaxError("Expression has too many nodes.")
    return node


def normalize_expression(text: str | Node) -> str:
    """Canonical qlib ``ClassName(arg,...)`` form; whitespace/alias independent."""
    return str(parse_expression(text))


def extended_window_size(node: Node) -> int:
    """Historical bars needed beyond the window (qlib's left extended window).

    qlib uses this to widen the data query before evaluation. Stage 1 evaluates
    strictly inside the frozen window, so the number is recorded in the spec as
    the warm-up requirement instead of triggering an extra data fetch.
    """
    if isinstance(node, (Feature, Constant)):
        return 0
    children = [extended_window_size(arg) for arg in node.args]
    if node.name in ELEMENTWISE:
        return children[0]
    if node.name in PAIRWISE:
        return max(children)
    if node.name == "If":
        return max(children)
    if node.name in SHIFT_OPERATORS:
        return children[0] + int(node.args[1].value)
    if node.name == "EMA":
        value = float(node.args[1].value)
        if value == 0:
            return children[0]
        if 0 < value < 1:
            return children[0] + int(math.log(1e-6) / math.log(1 - value))
        return children[0] + int(value) - 1
    if node.name in WINDOW_OPERATORS:
        return children[0] + int(node.args[1].value) - 1
    if node.name in PAIR_WINDOW_OPERATORS:
        return max(children[0], children[1]) + int(node.args[2].value) - 1
    raise ExpressionEvaluationError(f"No window rule for operator {node.name!r}.")


def expression_details(node: Node) -> dict[str, Any]:
    """Declarative metadata shared by the candidate, spec and view layers."""
    features: set[str] = set()
    operators: set[str] = set()

    def walk(current: Node) -> None:
        if isinstance(current, Feature):
            features.add(current.name)
        elif isinstance(current, Operator):
            operators.add(current.name)
            for argument in current.args:
                walk(argument)

    walk(node)
    return {
        "expression": str(node),
        "features": sorted(features),
        "operators": sorted(operators),
        "warmup_bars": extended_window_size(node),
        "causal": True,
        "schema_version": FACTOR_SCHEMA_VERSION,
    }
