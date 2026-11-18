"""Factor expression grammar built on DEAP and gplearn.

DEAP owns the typed primitive set and tree generation
(``PrimitiveSetTyped.addPrimitive`` / ``addTerminal`` / ``addEphemeralConstant``,
``genGrow`` / ``genFull`` / ``genHalfAndHalf``, ``PrimitiveTree``); gplearn's
``make_function`` owns the function-set declaration with its arity and closure
checks on zero / negative inputs. Operator names, arities and the ``$feature``
syntax come directly from stage 1's ``research_engine.expressions``.

Only one small adaptation is needed: DEAP's ``generate`` condition looks at
height/depth but not at the requested type, while our DSL requires a *literal*
window argument. ``_typed_generate`` reproduces DEAP's depth-first stack and
stop condition, adding only ``type_ is WINDOW`` as a forced terminal case.

The DEAP tree is never executed. Its gplearn stand-in callables only declare
arity/closure; actual numeric evaluation is stage 1's ``operators.py`` (pandas
rolling / ewm / corr). Every emitted string is re-parsed by stage 1 before it
becomes a ``FactorCandidate``, so the generator cannot leave the DSL.

A second, finite grammar is qlib Alpha158-style string templates (``{f}`` /
``{w}`` slots), enumerated deterministically from source-declared columns.
"""

from __future__ import annotations

import functools
import importlib.metadata
import random
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from deap import gp
from gplearn.functions import make_function

from dynaloop.research_engine.expressions import (
    OPERATOR_ARITY,
    PAIR_WINDOW_OPERATORS,
    SHIFT_OPERATORS,
    WINDOW_OPERATORS,
    normalize_expression,
    parse_expression,
)

GRAMMAR_SCHEMA_VERSION = 1


class SERIES:
    """DEAP type tag for a factor value column."""


class WINDOW:
    """DEAP type tag for a literal rolling-window argument."""


Primitive = gp.Primitive
PrimitiveSet = gp.PrimitiveSetTyped
DEFAULT_DEPTH = (1, 3)
DEFAULT_METHOD = "half_and_half"
METHODS = ("grow", "full", "half_and_half")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_WEIGHT_BUDGET = 16

# Default numeric subset of qlib's OpsList; callers may pass any subset of
# OPERATOR_ARITY to default_grammar(). This is a default, not a capability cap.
DEFAULT_NUMERIC_PRIMITIVES: tuple[str, ...] = (
    "Abs", "Sign",
    "Add", "Sub", "Mul", "Div",
    "Ref", "Delta",
    "Mean", "Sum", "Std", "Var", "Max", "Min", "Med", "Rank", "EMA", "WMA",
    "Corr", "Cov",
    "If",
)


class GrammarError(ValueError):
    """The grammar cannot produce a valid factor expression."""


def _protected_division(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    safe = np.where(np.abs(b) > 1e-3, b, 1.0)
    return np.where(np.abs(b) > 1e-3, np.divide(a, safe), 1.0)


def _protected_power(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.power(np.abs(a), np.clip(b, -2.0, 2.0))


def _protected_log(a: np.ndarray) -> np.ndarray:
    return np.log(np.abs(a) + 1e-6)


def _stand_in(name: str, arity: int) -> Any:
    """gplearn ``make_function`` callable: real elementwise ops, structural stubs.

    Time-series operators cannot be meaningfully applied to a length-10 vector
    with a scalar window; they are declared (and go through gplearn's closure
    check) but their numbers are always computed by stage 1's operators.
    """
    elementwise: dict[str, Any] = {
        "Abs": np.abs,
        "Sign": np.sign,
        "Log": _protected_log,
        "Not": lambda x: np.where(x != 0, 0.0, 1.0),
        "Add": np.add,
        "Sub": np.subtract,
        "Mul": np.multiply,
        "Div": _protected_division,
        "Power": _protected_power,
        "Greater": np.maximum,
        "Less": np.minimum,
        "Gt": lambda a, b: np.greater(a, b).astype(float),
        "Ge": lambda a, b: np.greater_equal(a, b).astype(float),
        "Lt": lambda a, b: np.less(a, b).astype(float),
        "Le": lambda a, b: np.less_equal(a, b).astype(float),
        "Eq": lambda a, b: np.equal(a, b).astype(float),
        "Ne": lambda a, b: np.not_equal(a, b).astype(float),
        "And": lambda a, b: np.logical_and(a, b).astype(float),
        "Or": lambda a, b: np.logical_or(a, b).astype(float),
        "If": lambda c, a, b: np.where(c, a, b),
    }
    if name in elementwise:
        return elementwise[name]
    if arity == 2:
        return lambda x, w: x
    if arity == 3:
        return lambda x, y, w: x
    raise GrammarError(f"Cannot declare a stand-in for {name!r} with arity {arity}.")


def function_set(primitives: Sequence[str]) -> dict[str, Any]:
    """gplearn's ``make_function`` validates arity and closure for each node."""
    result: dict[str, Any] = {}
    for name in primitives:
        if name not in OPERATOR_ARITY:
            raise GrammarError(f"Unknown qlib operator: {name!r}.")
        arity = OPERATOR_ARITY[name][0]
        result[name] = make_function(
            function=_stand_in(name, arity),
            name=name,
            arity=arity,
            wrap=False,
        )
    return result


def primitive_arg_types(name: str) -> tuple[type, ...]:
    """Typed arguments derived from stage 1's operator declaration."""
    if name in WINDOW_OPERATORS or name in SHIFT_OPERATORS:
        return (SERIES, WINDOW)
    if name in PAIR_WINDOW_OPERATORS:
        return (SERIES, SERIES, WINDOW)
    return (SERIES,) * OPERATOR_ARITY[name][0]


@dataclass(frozen=True, slots=True)
class FactorGrammar:
    """Immutable description of the random-expression grammar."""

    features: tuple[str, ...]
    windows: tuple[int, ...]
    primitives: tuple[str, ...] = DEFAULT_NUMERIC_PRIMITIVES
    init_depth: tuple[int, int] = DEFAULT_DEPTH
    init_method: str = DEFAULT_METHOD
    max_nodes: int = 48

    def __post_init__(self) -> None:
        low, high = self.init_depth
        if not isinstance(low, int) or not isinstance(high, int) or low < 1 or high < low:
            raise GrammarError("init_depth must be (min, max) with 1 <= min <= max.")
        if self.init_method not in METHODS:
            raise GrammarError(f"init_method must be one of {METHODS}.")
        if self.max_nodes < 1:
            raise GrammarError("max_nodes must be positive.")
        if not self.features or not self.windows or not self.primitives:
            raise GrammarError("A grammar needs features, windows and primitives.")
        if any(not isinstance(value, int) or value < 1 for value in self.windows):
            raise GrammarError("Windows must be positive integers.")

    def to_dict(self) -> dict[str, Any]:
        def version(name: str) -> str | None:
            try:
                return importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                return None

        return {
            "schema_version": GRAMMAR_SCHEMA_VERSION,
            "engine": "deap.PrimitiveSetTyped + gp.generate + gplearn.make_function",
            "primitives": [
                {"name": name, "arity": OPERATOR_ARITY[name][0],
                 "args": [kind.__name__ for kind in primitive_arg_types(name)]}
                for name in self.primitives
            ],
            "features": list(self.features),
            "windows": list(self.windows),
            "init_depth": list(self.init_depth),
            "init_method": self.init_method,
            "max_nodes": self.max_nodes,
            "library_versions": {"deap": version("deap"), "gplearn": version("gplearn")},
        }


def default_grammar(
    features: Sequence[str],
    windows: Sequence[int],
    *,
    primitives: Sequence[str] = DEFAULT_NUMERIC_PRIMITIVES,
    init_depth: tuple[int, int] = DEFAULT_DEPTH,
    init_method: str = DEFAULT_METHOD,
    max_nodes: int = 48,
) -> FactorGrammar:
    clean = tuple(
        dict.fromkeys(
            name for name in features
            if isinstance(name, str) and _IDENTIFIER.match(name)
        )
    )
    if not clean:
        raise GrammarError("No source-declared feature names can be used as $features.")
    return FactorGrammar(
        features=clean,
        windows=tuple(int(value) for value in windows),
        primitives=tuple(primitives),
        init_depth=init_depth,
        init_method=init_method,
        max_nodes=max_nodes,
    )


def _weighted(options: Sequence[Any], keys: Sequence[str], weights: Mapping[str, float] | None) -> list[Any]:
    """DEAP samples ``random.choice`` uniformly, so policy weights become copies."""
    items = list(options)
    if not weights:
        return items
    raw = np.array([max(float(weights.get(key, 0.0)), 0.0) for key in keys], dtype=float)
    if raw.sum() <= 0:
        return items
    counts = np.maximum(1, np.round(raw / raw.sum() * _WEIGHT_BUDGET).astype(int))
    expanded: list[Any] = []
    for option, count in zip(items, counts):
        expanded.extend([option] * int(count))
    return expanded


def _constant(value: int) -> int:
    return value


def build_primitive_set(
    grammar: FactorGrammar,
    weights: Mapping[str, float] | None = None,
) -> gp.PrimitiveSetTyped:
    """Construct the DEAP typed set; gplearn declares every function node."""
    pset = gp.PrimitiveSetTyped("factor", [], SERIES)
    functions = function_set(grammar.primitives)
    for name in grammar.primitives:
        pset.addPrimitive(functions[name], list(primitive_arg_types(name)), SERIES, name=name)
    for feature in grammar.features:
        pset.addTerminal(feature, SERIES, name=feature)
    for window in grammar.windows:
        pset.addEphemeralConstant(
            f"w{window}", functools.partial(_constant, window), WINDOW
        )
    pset.primitives[SERIES] = _weighted(
        pset.primitives[SERIES],
        [f"primitive:{item.name}" for item in pset.primitives[SERIES]],
        weights,
    )
    pset.terminals[SERIES] = _weighted(
        pset.terminals[SERIES],
        [f"feature:{item.value}" for item in pset.terminals[SERIES]],
        weights,
    )
    pset.terminals[WINDOW] = _weighted(
        pset.terminals[WINDOW],
        [f"window:{grammar.windows[index]}" for index in range(len(pset.terminals[WINDOW]))],
        weights,
    )
    return pset


def describe_primitive_set(pset: gp.PrimitiveSetTyped) -> dict[str, Any]:
    return {
        "primitives": [item.name for item in pset.primitives[SERIES]],
        "features": [str(item.value) for item in pset.terminals[SERIES]],
        "window_terminals": [str(item.name) for item in pset.terminals[WINDOW]],
        "terminal_ratio": pset.terminalRatio,
    }


def _typed_generate(
    pset: gp.PrimitiveSetTyped,
    min_: int,
    max_: int,
    method: str,
    rng: random.Random,
) -> gp.PrimitiveTree:
    """DEAP ``generate`` DFS stack, with WINDOW forced to a terminal."""
    height = rng.randint(min_, max_)
    stack: list[tuple[int, type]] = [(0, SERIES)]
    expression: list[Any] = []
    while stack:
        depth, type_ = stack.pop()
        stop = depth == height or (
            method == "grow"
            and depth >= min_
            and rng.random() < pset.terminalRatio
        )
        if type_ is WINDOW or stop:
            terminal = rng.choice(pset.terminals[type_])
            if type(terminal) is gp.MetaEphemeral:
                terminal = terminal()
            expression.append(terminal)
        else:
            primitive = rng.choice(pset.primitives[type_])
            expression.append(primitive)
            for argument in reversed(primitive.args):
                stack.append((depth + 1, argument))
    return gp.PrimitiveTree(expression)


def _render(tree: gp.PrimitiveTree) -> tuple[str, list[str]]:
    tokens = list(tree)
    position = 0
    parts: list[str] = []

    def build() -> str:
        nonlocal position
        node = tokens[position]
        position += 1
        if isinstance(node, gp.Primitive):
            parts.append(f"primitive:{node.name}")
            arguments = [build() for _ in range(node.arity)]
            return f"{node.name}({', '.join(arguments)})"
        if node.ret is WINDOW:
            parts.append(f"window:{node.value}")
            return str(node.value)
        parts.append(f"feature:{node.value}")
        return "$" + str(node.value)

    text = build()
    if position != len(tokens):
        raise GrammarError("The generated prefix expression is incomplete.")
    return text, parts


def generate_expression(
    grammar: FactorGrammar,
    rng: np.random.Generator,
    *,
    weights: Mapping[str, float] | None = None,
    max_attempts: int = 32,
) -> tuple[str, tuple[str, ...]]:
    """Return a normalised DSL expression and the production keys it used."""
    pset = build_primitive_set(grammar, weights)
    low, high = grammar.init_depth
    for _ in range(max_attempts):
        python_seed = int(rng.integers(0, 2**32))
        local_random = random.Random(python_seed)
        method = grammar.init_method
        if method == "half_and_half":
            method = "grow" if local_random.random() < 0.5 else "full"
        tree = _typed_generate(pset, low, high, method, local_random)
        if len(tree) > grammar.max_nodes:
            continue
        text, parts = _render(tree)
        try:
            normalised = normalize_expression(parse_expression(text))
        except ValueError:
            continue
        return normalised, tuple(sorted(set(parts)))
    raise GrammarError("Could not generate a valid expression within the attempt limit.")


@dataclass(frozen=True, slots=True)
class FactorTemplate:
    """An Alpha158-style string template with ``{f}`` / ``{w}`` slots."""

    name: str
    pattern: str
    required_features: tuple[str, ...] = ()

    def render(self, feature: str, window: int) -> str:
        return self.pattern.format(f=feature, w=window)


# ``required_features`` declares extra fixed columns. A source that lacks them
# simply gets no panel (AGENTS.md §1.11: no column, no explanation).
DEFAULT_TEMPLATES: tuple[FactorTemplate, ...] = (
    FactorTemplate("momentum", "${f} / Ref(${f}, {w}) - 1"),
    FactorTemplate("mean_reversion", "(${f} - Mean(${f}, {w})) / Std(${f}, {w})"),
    FactorTemplate("ema_trend", "EMA(${f}, {w}) / ${f} - 1"),
    FactorTemplate("volatility", "Std(${f} / Ref(${f}, 1) - 1, {w})"),
    FactorTemplate("breakout", "${f} / Max(${f}, {w}) - 1"),
    FactorTemplate("acceleration", "Delta(${f}, 1) - Delta(${f}, {w})"),
    FactorTemplate(
        "range_position",
        "($close - Min($low, {w})) / (Max($high, {w}) - Min($low, {w}))",
        ("close", "low", "high"),
    ),
    FactorTemplate(
        "volume_confirmation",
        "($close / Ref($close, 1) - 1) * ($volume / Mean($volume, {w}) - 1)",
        ("close", "volume"),
    ),
)


@dataclass(frozen=True, slots=True)
class TemplateInstance:
    """One fully rendered, validated member of the finite template family."""

    template: str
    expression: str
    feature: str
    window: int


def available_templates(
    features: Sequence[str],
    windows: Sequence[int],
    *,
    templates: Sequence[FactorTemplate] = DEFAULT_TEMPLATES,
) -> tuple[TemplateInstance, ...]:
    """Deterministic, source-declared enumeration of the whole template space."""
    usable = [name for name in features if isinstance(name, str) and _IDENTIFIER.match(name)]
    if not usable:
        raise GrammarError("No source-declared feature names can be used as $features.")
    if not windows or any(not isinstance(value, int) or value < 1 for value in windows):
        raise GrammarError("windows must be a non-empty sequence of positive integers.")
    instances: list[TemplateInstance] = []
    seen: set[str] = set()
    for template in templates:
        if any(name not in usable for name in template.required_features):
            continue
        for feature in usable:
            for window in windows:
                try:
                    expression = normalize_expression(parse_expression(template.render(feature, window)))
                except ValueError as error:
                    raise GrammarError(f"Template {template.name!r} is invalid: {error}") from error
                if expression in seen:
                    continue
                seen.add(expression)
                instances.append(
                    TemplateInstance(
                        template=template.name,
                        expression=expression,
                        feature=feature,
                        window=window,
                    )
                )
    if not instances:
        raise GrammarError("The source-declared columns match no available template.")
    return tuple(sorted(instances, key=lambda item: (item.template, item.feature, item.window)))


def template_choice_keys(
    features: Sequence[str],
    windows: Sequence[int],
    *,
    templates: Sequence[FactorTemplate] = DEFAULT_TEMPLATES,
) -> tuple[str, ...]:
    """Keys the policy distributes over for the template generator."""
    instances = available_templates(features, windows, templates=templates)
    return tuple(sorted({f"template:{item.template}" for item in instances}))
