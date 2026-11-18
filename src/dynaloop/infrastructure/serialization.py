"""Canonical serialization and fingerprints for reproducible factor runs."""

from __future__ import annotations

import hashlib
import json
import platform
from typing import Any


def canonical_json(payload: Any) -> str:
    """Deterministic JSON; NaN/Infinity are forbidden so specs stay portable."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def fingerprint(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def library_versions() -> dict[str, str | None]:
    """Same observational metadata the backtest engine records in its spec."""
    versions: dict[str, str | None] = {"python": platform.python_version()}
    for name in ("numpy", "pandas"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", None)
        except ImportError:
            versions[name] = None
    return versions
