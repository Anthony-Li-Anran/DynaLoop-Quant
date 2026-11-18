"""JSON-file persistence for closed-loop run results, keyed by run fingerprint."""

from __future__ import annotations

from dynaloop.infrastructure import JsonMappingStore

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class LoopStoreError(RuntimeError):
    """Raised when stored loop runs are unreadable or invalid."""


class LoopRunStore:
    """Append-only style CRUD: a stored run is addressed by its fingerprint.

    Re-running an identical configuration reproduces the same fingerprint and
    refreshes the stored copy without creating a duplicate entry.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._store = JsonMappingStore(path, error_type=LoopStoreError, label='Stored loop runs', recover_invalid=False)

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, dict[str, Any]]:
        return self._store.read()

    def list_all(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            value for _, value in sorted(
                self._read().items(),
                key=lambda item: item[1].get("created_at", ""),
                reverse=True,
            )
        )

    def get(self, fingerprint: str) -> dict[str, Any] | None:
        return self._read().get(fingerprint)

    def save(self, result: Mapping[str, Any], *, origin: str) -> dict[str, Any]:
        fingerprint = str(result["fingerprint"])
        with self._store.transaction() as entries:
            existing = entries.get(fingerprint) or {}
            entry = {
                **existing,
                "fingerprint": fingerprint,
                "origin": origin,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "round_count": len(result.get("rounds") or []),
                "final_reliability": result.get("final_reliability"),
                "run_ids": list(result.get("run_ids") or []),
                "experiment_id": (result.get("spec") or {}).get("config", {}).get(
                    "experiment_id"
                ),
                "result": dict(result),
            }
            entries[fingerprint] = entry
        return entry
