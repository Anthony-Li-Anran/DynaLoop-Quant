"""Serialization helpers for source-agnostic acquisition requests."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from dynaloop.data.domain.errors import DataDefinitionError

DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "access_key",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "authorization",
        "credential",
        "credentials",
        "private_key",
    }
)


def _fold(name: str) -> str:
    return "".join(character for character in name.casefold() if character.isalnum())


def normalize_spec(
    spec: Mapping[str, object],
    *,
    sensitive_keys: Iterable[str] = DEFAULT_SENSITIVE_KEYS,
) -> tuple[tuple[str, str], ...]:
    """Validate a request spec and return stable (key, JSON text) pairs.

    Credential-bearing fields are rejected so persisted acquisition lineage can
    never carry secrets. The blocked-name set is caller-configurable, so the
    policy itself stays with the integration layer.
    """
    if not isinstance(spec, Mapping):
        raise DataDefinitionError("Acquisition spec must be a mapping.")
    blocked = {_fold(name) for name in sensitive_keys}
    pairs: list[tuple[str, str]] = []
    for key, value in spec.items():
        if not isinstance(key, str) or not key.strip():
            raise DataDefinitionError("Acquisition spec keys must be non-empty strings.")
        if _fold(key) in blocked:
            raise DataDefinitionError(
                f"Acquisition spec must not contain credential field '{key}'."
            )
        try:
            encoded = json.dumps(
                value, sort_keys=True, ensure_ascii=False, allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise DataDefinitionError(
                f"Acquisition spec value for '{key}' is not JSON-serializable."
            ) from exc
        pairs.append((key, encoded))
    return tuple(sorted(pairs))
