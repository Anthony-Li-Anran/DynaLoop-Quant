"""Generic adapter registry plumbing shared by acquisition integrations."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from dynaloop.data.domain.errors import DataDefinitionError

AdapterT = TypeVar("AdapterT")


def _freeze_descriptor(
    descriptor: Mapping[str, object] | None,
) -> tuple[tuple[str, Any], ...]:
    """Validate and normalize descriptor values without interpreting their meaning."""
    if descriptor is None:
        return ()
    if not isinstance(descriptor, Mapping):
        raise DataDefinitionError("Adapter descriptor must be a mapping.")
    try:
        normalized = json.loads(
            json.dumps(dict(descriptor), sort_keys=True, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise DataDefinitionError("Adapter descriptor must be JSON-serializable.") from exc
    return tuple(sorted(normalized.items()))


@dataclass(frozen=True, slots=True)
class AdapterRegistration(Generic[AdapterT]):
    """One registered adapter: a stable key, a factory, and catalog metadata."""

    key: str
    factory: Callable[[], AdapterT]
    descriptor: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise DataDefinitionError("Adapter key must be a non-empty string.")
        if not callable(self.factory):
            raise DataDefinitionError("Adapter factory must be callable.")


class AdapterRegistry(Generic[AdapterT]):
    """Minimal key-to-factory container; it deliberately knows nothing about adapters."""

    def __init__(self) -> None:
        self._entries: dict[str, AdapterRegistration[AdapterT]] = {}

    def register(
        self,
        key: str,
        factory: Callable[[], AdapterT],
        *,
        descriptor: Mapping[str, object] | None = None,
    ) -> AdapterRegistration[AdapterT]:
        entry = AdapterRegistration(
            key=key.strip() if isinstance(key, str) else key,
            factory=factory,
            descriptor=_freeze_descriptor(descriptor),
        )
        if entry.key in self._entries:
            raise DataDefinitionError(f"Adapter '{entry.key}' is already registered.")
        self._entries[entry.key] = entry
        return entry

    def unregister(self, key: str) -> bool:
        """Remove an entry so runtime configurations can be replaced or deleted."""
        if key not in self._entries:
            return False
        del self._entries[key]
        return True

    def resolve(self, key: str) -> AdapterRegistration[AdapterT]:
        try:
            return self._entries[key]
        except (KeyError, TypeError) as exc:
            raise DataDefinitionError(f"Adapter '{key}' is not registered.") from exc

    def create(self, key: str) -> AdapterT:
        return self.resolve(key).factory()

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def descriptors(self) -> tuple[dict[str, Any], ...]:
        """Return catalog rows; the registry key always wins over descriptor metadata."""
        return tuple(
            {**dict(entry.descriptor), "key": entry.key}
            for entry in (self._entries[key] for key in self.keys())
        )
