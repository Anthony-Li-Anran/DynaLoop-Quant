"""Versioned, immutable market environment registry.

The public surface follows Gymnasium's ``registration`` module (``register``,
``spec``, ``latest``, ``make``) because that is the mature naming for an
environment registry. The semantics differ in one deliberate place:
Gymnasium overwrites an existing id, while the system contract section 1.5
requires every write-back to produce a new version. Re-registering the same
``(environment_id, version)`` with a different definition is refused here.

No ``gym.Env`` is involved: a market environment is a frozen evaluation
window, not an MDP step loop, so Gymnasium's checker / TimeLimit wrappers
and its global mutable registry do not apply.
"""

from __future__ import annotations

from typing import Any, Iterable

from dynaloop.market_environment.definitions import (
    EnvironmentDefinition,
    EnvironmentDefinitionError,
    EnvironmentReference,
)
from dynaloop.research_engine.spec import fingerprint

ENVIRONMENT_SCHEMA_VERSION = 1


class EnvironmentRegistryError(EnvironmentDefinitionError):
    """Raised when a registry operation would overwrite a frozen definition."""


def definition_payload(definition: EnvironmentDefinition) -> dict[str, Any]:
    """JSON-safe view of a definition, including its external references."""
    time_range = definition.time_range
    return {
        "environment_id": definition.environment_id,
        "version": definition.version,
        "environment_type": definition.environment_type.value,
        "source": definition.source,
        "time_range": None
        if time_range is None
        else {"start": time_range.start.isoformat(), "end": time_range.end.isoformat()},
        "applicability": list(definition.applicability),
        "limitations": list(definition.limitations),
        "artifact_references": [
            {
                "artifact_type": reference.artifact_type.value,
                "artifact_id": reference.artifact_id,
                "version": reference.version,
            }
            for reference in definition.artifact_references
        ],
    }


class EnvironmentRegistry:
    """Registry of frozen definitions keyed by ``(environment_id, version)``."""

    def __init__(self, definitions: Iterable[EnvironmentDefinition] = ()) -> None:
        self._specs: dict[tuple[str, str], EnvironmentDefinition] = {}
        self._order: list[tuple[str, str]] = []
        for definition in definitions:
            self.register(definition)

    @staticmethod
    def key(reference: EnvironmentReference) -> tuple[str, str]:
        return (reference.environment_id, reference.version)

    def register(self, definition: EnvironmentDefinition) -> EnvironmentReference:
        """Register once; identical re-registration is idempotent, changes are not."""
        if not isinstance(definition, EnvironmentDefinition):
            raise EnvironmentRegistryError("definition must be an EnvironmentDefinition.")
        key = (definition.environment_id, definition.version)
        existing = self._specs.get(key)
        if existing is not None:
            if existing != definition:
                raise EnvironmentRegistryError(
                    f"Environment {definition.environment_id}@{definition.version} is frozen; "
                    "publish a new version instead of overwriting it."
                )
            return definition.reference
        self._specs[key] = definition
        self._order.append(key)
        return definition.reference

    def spec(self, reference: EnvironmentReference) -> EnvironmentDefinition:
        """Look up an exact version; no implicit latest-version rewriting."""
        return self._get(reference)

    def latest(self, environment_id: str) -> EnvironmentDefinition:
        """Most recently registered version of one environment id."""
        for key in reversed(self._order):
            if key[0] == environment_id:
                return self._specs[key]
        raise EnvironmentRegistryError(f"No environment registered for {environment_id!r}.")

    def references(self) -> tuple[EnvironmentReference, ...]:
        return tuple(self._specs[key].reference for key in self._order)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ENVIRONMENT_SCHEMA_VERSION,
            "definitions": [definition_payload(self._specs[key]) for key in self._order],
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())

    def _get(self, reference: EnvironmentReference) -> EnvironmentDefinition:
        if not isinstance(reference, EnvironmentReference):
            raise EnvironmentRegistryError("reference must be an EnvironmentReference.")
        try:
            return self._specs[self.key(reference)]
        except KeyError as exc:
            raise EnvironmentRegistryError(
                f"Unknown environment {reference.environment_id}@{reference.version}."
            ) from exc


__all__ = [
    "ENVIRONMENT_SCHEMA_VERSION",
    "EnvironmentRegistry",
    "EnvironmentRegistryError",
    "definition_payload",
]
