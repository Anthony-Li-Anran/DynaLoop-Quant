"""Pluggable candidate generators and the shared generation request.

``CandidateGenerator`` is the replacement point for a future LM: a language
model only has to implement ``choice_keys`` / ``sample`` / ``spec`` and emit
stage 1 ``FactorCandidate`` objects. Two real, deterministic implementations
ship here: a DEAP/gplearn typed-grammar sampler and a finite Alpha158-style
template sampler. No stub or placeholder implementation is registered.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from dynaloop.model.grammar import (
    DEFAULT_DEPTH,
    DEFAULT_METHOD,
    DEFAULT_NUMERIC_PRIMITIVES,
    DEFAULT_TEMPLATES,
    FactorGrammar,
    FactorTemplate,
    GrammarError,
    TemplateInstance,
    available_templates,
    default_grammar,
    generate_expression,
    template_choice_keys,
)
from dynaloop.research_engine.candidates import FactorCandidate
from dynaloop.research_engine.spec import fingerprint

GENERATOR_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """Source-declared feature/window space for one sampling round."""

    features: tuple[str, ...]
    windows: tuple[int, ...]
    batch_size: int
    round_index: int = 0
    init_method: str = DEFAULT_METHOD
    init_depth: tuple[int, int] = DEFAULT_DEPTH
    max_nodes: int = 48

    def __post_init__(self) -> None:
        if not self.features:
            raise GrammarError("A generation request needs source-declared features.")
        if not self.windows:
            raise GrammarError("A generation request needs at least one window.")
        if not isinstance(self.batch_size, int) or self.batch_size < 1:
            raise GrammarError("batch_size must be a positive integer.")
        if not isinstance(self.round_index, int) or self.round_index < 0:
            raise GrammarError("round_index must be a non-negative integer.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GENERATOR_SCHEMA_VERSION,
            "features": list(self.features),
            "windows": list(self.windows),
            "batch_size": self.batch_size,
            "round_index": self.round_index,
            "init_method": self.init_method,
            "init_depth": list(self.init_depth),
            "max_nodes": self.max_nodes,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class GeneratedCandidate:
    """A factor candidate plus the production rules that produced it."""

    candidate: FactorCandidate
    choice: str
    parts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.candidate.factor_id,
            "expression": self.candidate.expression,
            "choice": self.choice,
            "parts": list(self.parts),
        }


@runtime_checkable
class CandidateGenerator(Protocol):
    """The model's public protocol; an LM implementation can replace this."""

    name: str

    def choice_keys(self, request: GenerationRequest) -> tuple[str, ...]: ...

    def spec(self, request: GenerationRequest) -> dict[str, Any]: ...

    def sample(
        self,
        request: GenerationRequest,
        weights: Mapping[str, float],
        rng: np.random.Generator,
    ) -> tuple[GeneratedCandidate, ...]: ...


class GrammarCandidateGenerator:
    """Random typed trees via DEAP's ``generate`` and gplearn function sets."""

    name = "grammar"

    def __init__(self, primitives: Sequence[str] = DEFAULT_NUMERIC_PRIMITIVES) -> None:
        self.primitives = tuple(primitives)

    def grammar(self, request: GenerationRequest) -> FactorGrammar:
        return default_grammar(
            request.features,
            request.windows,
            primitives=self.primitives,
            init_depth=request.init_depth,
            init_method=request.init_method,
            max_nodes=request.max_nodes,
        )

    def choice_keys(self, request: GenerationRequest) -> tuple[str, ...]:
        grammar = self.grammar(request)
        keys = [f"primitive:{name}" for name in grammar.primitives]
        keys += [f"feature:{name}" for name in grammar.features]
        keys += [f"window:{value}" for value in grammar.windows]
        return tuple(sorted(set(keys)))

    def spec(self, request: GenerationRequest) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "typed_grammar",
            "grammar": self.grammar(request).to_dict(),
            "primitives": list(self.primitives),
        }

    def sample(
        self,
        request: GenerationRequest,
        weights: Mapping[str, float],
        rng: np.random.Generator,
    ) -> tuple[GeneratedCandidate, ...]:
        grammar = self.grammar(request)
        generated: list[GeneratedCandidate] = []
        for _ in range(request.batch_size):
            expression, parts = generate_expression(grammar, rng, weights=weights)
            generated.append(
                GeneratedCandidate(
                    candidate=FactorCandidate.from_expression(expression),
                    choice=parts[0] if parts else "primitive:root",
                    parts=parts,
                )
            )
        return tuple(generated)


class TemplateCandidateGenerator:
    """Finite, fully enumerable Alpha158-style template family."""

    name = "template"

    def __init__(self, templates: Sequence[FactorTemplate] = DEFAULT_TEMPLATES) -> None:
        self.templates = tuple(templates)

    def instances(self, request: GenerationRequest) -> tuple[TemplateInstance, ...]:
        return available_templates(request.features, request.windows, templates=self.templates)

    def choice_keys(self, request: GenerationRequest) -> tuple[str, ...]:
        return template_choice_keys(request.features, request.windows, templates=self.templates)

    def spec(self, request: GenerationRequest) -> dict[str, Any]:
        instances = self.instances(request)
        return {
            "name": self.name,
            "kind": "alpha158_templates",
            "templates": [
                {
                    "name": item.name,
                    "pattern": item.pattern,
                    "required_features": list(item.required_features),
                }
                for item in self.templates
            ],
            "available_instances": len(instances),
            "choice_keys": list(self.choice_keys(request)),
        }

    def enumerate_candidates(self, request: GenerationRequest) -> tuple[FactorCandidate, ...]:
        """The whole finite space, in deterministic lexicographic order."""
        return tuple(
            FactorCandidate.from_expression(item.expression)
            for item in self.instances(request)
        )

    def sample(
        self,
        request: GenerationRequest,
        weights: Mapping[str, float],
        rng: np.random.Generator,
    ) -> tuple[GeneratedCandidate, ...]:
        instances = self.instances(request)
        grouped: dict[str, list[TemplateInstance]] = {}
        for instance in instances:
            grouped.setdefault(f"template:{instance.template}", []).append(instance)
        keys = sorted(grouped)
        raw = np.array([max(float(weights.get(key, 0.0)), 0.0) for key in keys], dtype=float)
        probability = raw / raw.sum() if raw.sum() > 0 else None
        generated: list[GeneratedCandidate] = []
        for _ in range(request.batch_size):
            key = keys[int(rng.choice(len(keys), p=probability))]
            instance = grouped[key][int(rng.integers(len(grouped[key])))]
            parts = (
                key,
                f"feature:{instance.feature}",
                f"window:{instance.window}",
            )
            generated.append(
                GeneratedCandidate(
                    candidate=FactorCandidate.from_expression(instance.expression),
                    choice=key,
                    parts=parts,
                )
            )
        return tuple(generated)


GENERATOR_REGISTRY: dict[str, type] = {
    "grammar": GrammarCandidateGenerator,
    "template": TemplateCandidateGenerator,
}


def register_generator(name: str, generator_type: type) -> None:
    if not name or not isinstance(name, str):
        raise GrammarError("A generator name must be a non-empty string.")
    GENERATOR_REGISTRY[name] = generator_type


def build_generator(name_or_path: str, **kwargs: Any) -> CandidateGenerator:
    """Resolve by registry name or ``module.Class`` (same rule as build_strategy)."""
    if "." in name_or_path:
        module_name, class_name = name_or_path.rsplit(".", 1)
        generator_type = getattr(importlib.import_module(module_name), class_name)
    elif name_or_path in GENERATOR_REGISTRY:
        generator_type = GENERATOR_REGISTRY[name_or_path]
    else:
        raise GrammarError(f"Unknown candidate generator: {name_or_path!r}.")
    generator = generator_type(**kwargs)
    if not isinstance(generator, CandidateGenerator):
        raise GrammarError(f"{name_or_path!r} does not implement CandidateGenerator.")
    return generator
