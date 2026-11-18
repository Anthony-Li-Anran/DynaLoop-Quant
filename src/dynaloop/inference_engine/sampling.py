"""Deterministic candidate-group sampling for one research round.

``num_generations`` / group semantics follow TRL's ``GRPOTrainer`` (a group of
``G`` completions sampled for the same context), while reproducibility uses
numpy's ``SeedSequence([seed, round_index])`` -> ``default_rng(PCG64)`` so each
round has its own stream and every round can be replayed from the recorded seed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from dynaloop.model.generators import (
    GenerationRequest,
    GeneratedCandidate,
    CandidateGenerator,
)
from dynaloop.research_engine.candidates import FactorCandidate
from dynaloop.research_engine.exploration import ExplorationPolicy, PolicyError
from dynaloop.research_engine.spec import fingerprint, library_versions

SAMPLING_SCHEMA_VERSION = 1
_UINT32 = 2**32


@dataclass(frozen=True, slots=True)
class SamplingRequest:
    """A group request; ``group_size`` is the intended number of candidates."""

    seed: int
    round_index: int
    group_size: int
    features: tuple[str, ...]
    windows: tuple[int, ...]
    init_method: str = "half_and_half"
    init_depth: tuple[int, int] = (1, 3)
    max_nodes: int = 48

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise PolicyError("seed must be an integer.")
        if not isinstance(self.round_index, int) or self.round_index < 0:
            raise PolicyError("round_index must be a non-negative integer.")
        if not isinstance(self.group_size, int) or self.group_size < 1:
            raise PolicyError("group_size must be a positive integer.")

    def generation_request(self, batch_size: int) -> GenerationRequest:
        return GenerationRequest(
            features=self.features,
            windows=self.windows,
            batch_size=batch_size,
            round_index=self.round_index,
            init_method=self.init_method,
            init_depth=self.init_depth,
            max_nodes=self.max_nodes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SAMPLING_SCHEMA_VERSION,
            "seed": self.seed,
            "round_index": self.round_index,
            "group_size": self.group_size,
            "features": list(self.features),
            "windows": list(self.windows),
            "init_method": self.init_method,
            "init_depth": list(self.init_depth),
            "max_nodes": self.max_nodes,
        }

    def rng(self) -> np.random.Generator:
        entropy = [int(self.seed) % _UINT32, int(self.round_index) % _UINT32]
        return np.random.default_rng(np.random.SeedSequence(entropy))


@dataclass(frozen=True, slots=True)
class CandidateBatch:
    """The group of ``f1..fN`` consumed by Research Engine and Training Engine."""

    round_index: int
    candidates: tuple[FactorCandidate, ...]
    choices: tuple[str, ...]
    parts: tuple[tuple[str, ...], ...]
    spec: dict[str, Any]

    @property
    def factor_ids(self) -> tuple[str, ...]:
        return tuple(candidate.factor_id for candidate in self.candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "factor_ids": list(self.factor_ids),
            "expressions": [candidate.expression for candidate in self.candidates],
            "choices": list(self.choices),
            "parts": [list(items) for items in self.parts],
            "spec": self.spec,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


class InferenceEngine:
    """Stateless sampler: generation request + frozen policy -> candidate group."""

    def sample(
        self,
        generator: CandidateGenerator,
        policy: ExplorationPolicy,
        request: SamplingRequest,
        *,
        max_draws: int = 12,
    ) -> CandidateBatch:
        if not isinstance(generator, CandidateGenerator):
            raise PolicyError("generator must implement CandidateGenerator.")
        if max_draws < 1:
            raise PolicyError("max_draws must be a positive integer.")
        generation_request = request.generation_request(request.group_size)
        keys = generator.choice_keys(generation_request)
        probabilities = policy.probabilities(keys)
        weights: Mapping[str, float] = {
            key: float(value) for key, value in zip(keys, probabilities.tolist())
        }
        rng = request.rng()

        collected: dict[str, GeneratedCandidate] = {}
        for _ in range(max_draws):
            for generated in generator.sample(generation_request, weights, rng):
                collected.setdefault(generated.candidate.factor_id, generated)
                if len(collected) >= request.group_size:
                    break
            if len(collected) >= request.group_size:
                break
        ordered = tuple(collected.values())
        spec = {
            "schema_version": SAMPLING_SCHEMA_VERSION,
            "request": request.to_dict(),
            "realized_group_size": len(ordered),
            "draw_policy": {
                "max_draws": max_draws,
                "dedupe": "by_factor_id",
            },
            "generator": generator.spec(generation_request),
            "policy": policy.to_dict(),
            "policy_fingerprint": policy.fingerprint(),
            "choice_keys": list(keys),
            "choice_probabilities": [float(value) for value in probabilities.tolist()],
            "rng": {
                "algorithm": "numpy.default_rng(PCG64)",
                "entropy": [int(request.seed) % _UINT32, int(request.round_index) % _UINT32],
            },
            "library_versions": library_versions(),
        }
        return CandidateBatch(
            round_index=request.round_index,
            candidates=tuple(item.candidate for item in ordered),
            choices=tuple(item.choice for item in ordered),
            parts=tuple(item.parts for item in ordered),
            spec=spec,
        )
