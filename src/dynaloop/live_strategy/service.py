"""Facade combining collection, storage, retrieval and experience reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dynaloop.live_strategy.collector import (
    NullStrategyCollector,
    StrategyCollector,
)
from dynaloop.live_strategy.contracts import ExperienceEvent, ProviderReport
from dynaloop.live_strategy.experience import (
    DEFAULT_HALF_LIFE_DAYS,
    experience_report,
)
from dynaloop.live_strategy.index import retrieve_relevant
from dynaloop.live_strategy.store import StrategyLibraryStore


class LiveStrategyLibrary:
    def __init__(self, path: str | Path) -> None:
        self._store = StrategyLibraryStore(path)

    def refresh(
        self,
        collector: StrategyCollector | None = None,
        *,
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Harvest new strategies into the library; explicit status on failure."""
        source = collector or NullStrategyCollector()
        status: ProviderReport = source.status()
        created = 0
        fingerprints: list[str] = []
        if status.available:
            for entry in source.collect(query=query, limit=limit):
                was_created, fp = self._store.upsert_entry(entry)
                if was_created:
                    created += 1
                fingerprints.append(fp)
        return {
            "schema": "strategy-refresh/1",
            "status": status.to_dict(),
            "query": query,
            "created": created,
            "fingerprints": fingerprints,
            "not_a_claim": "harvested candidates are subjective references only",
        }

    def retrieve(
        self,
        *,
        query: str,
        decision_time: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Contextual, point-in-time-safe strategies for subjective reference."""
        return retrieve_relevant(
            self._store.list_entries(),
            query=query,
            decision_time=decision_time,
            top_k=top_k,
        )

    def record_experience(self, event: ExperienceEvent) -> str:
        """Attribute a simulated-execution outcome to referenced strategies."""
        return self._store.add_experience(event)

    def experience(
        self,
        *,
        as_of: str,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ) -> dict[str, dict[str, Any]]:
        return experience_report(
            self._store.list_experience(),
            as_of=as_of,
            half_life_days=half_life_days,
        )

    def snapshot(self, *, as_of: str) -> dict[str, Any]:
        """Read-only library overview with report-only experience scores."""
        entries = self._store.list_entries()
        return {
            "schema": "live-strategy-snapshot/1",
            "count": len(entries),
            "entries": entries,
            "experience": self.experience(as_of=as_of),
            "not_a_claim": "harvested strategies and experience stars are subjective, report-only",
        }


__all__ = ["LiveStrategyLibrary"]
