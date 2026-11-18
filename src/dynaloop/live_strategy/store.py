"""Append-only persistence for the living strategy library.

Two independent JSON mappings, both backed by the project's atomic
JsonMappingStore: one for strategy entries, one for experience events. Existing
entries are never rewritten by ingestion -- a changed strategy is a new
versioned entry with a new content fingerprint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dynaloop.infrastructure import JsonMappingStore
from dynaloop.infrastructure.serialization import fingerprint
from dynaloop.live_strategy.contracts import ExperienceEvent, StrategyEntry


class StrategyLibraryStore:
    def __init__(self, path: str | Path) -> None:
        self._entries = JsonMappingStore(path, label="strategy library")
        base = Path(path).with_suffix("")
        self._experience = JsonMappingStore(
            str(base) + "_experience.json", label="strategy experience ledger"
        )

    # -- strategy entries -------------------------------------------------
    def upsert_entry(self, entry: StrategyEntry) -> tuple[bool, str]:
        """Store an entry keyed by a stable id; return (created, fingerprint).

        A repeated id with an identical content fingerprint is a no-op. A
        repeated id with different content is stored under a versioned id so
        history is append-only and nothing is silently overwritten.
        """
        fp = entry.content_fingerprint()
        with self._entries.transaction() as entries:
            existing = entries.get(entry.entry_id)
            if existing is None:
                entries[entry.entry_id] = {**entry.to_dict(), "content_fingerprint": fp}
                return True, fp
            if existing.get("content_fingerprint") == fp:
                return False, fp
            versioned_id = f"{entry.entry_id}@{fp[:12]}"
            if versioned_id not in entries:
                payload = {**entry.to_dict(), "entry_id": versioned_id,
                           "content_fingerprint": fp}
                entries[versioned_id] = payload
            return True, fp

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        return self._entries.read().get(entry_id)

    def list_entries(self) -> list[dict[str, Any]]:
        return list(self._entries.read().values())

    # -- experience events ------------------------------------------------
    def add_experience(self, event: ExperienceEvent) -> str:
        fp = fingerprint(event.to_dict())
        with self._experience.transaction() as entries:
            if event.event_id not in entries:
                entries[event.event_id] = {**event.to_dict(), "content_fingerprint": fp}
        return fp

    def list_experience(self) -> list[dict[str, Any]]:
        return list(self._experience.read().values())


__all__ = ["StrategyLibraryStore"]
