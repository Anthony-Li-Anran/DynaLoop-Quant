"""Point-in-time contracts for the living strategy library.

A strategy entry is a *candidate practice harvested from the outside world*,
never a validated factor, signal verdict or return claim from this project.
Every entry carries three distinct times and a content fingerprint so that:

* it can only be consulted at or after ``available_at`` (no contract-level
  look-ahead -- a strategy published after the decision time is inadmissible);
* its provenance and exact bytes are auditable and reproducible.

Experience records are the only place where simulated-execution outcomes are
stored. They feed a report-only reputation score (see experience.py), never a
statistical effectiveness gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dynaloop.infrastructure.serialization import fingerprint

LIVE_STRATEGY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StrategyEntry:
    """One harvested strategy practice with full time and source provenance."""

    entry_id: str
    name: str
    author: str | None
    method: str
    regimes: tuple[str, ...]
    source_url: str
    source_name: str
    published_at: str | None
    collected_at: str
    available_at: str
    summary: str
    raw_excerpt: str | None = None
    extractor_version: str | None = None
    prompt_version: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")
        if not self.available_at:
            raise ValueError("available_at is mandatory for point-in-time alignment")
        if not self.source_url:
            raise ValueError("source_url must be non-empty for provenance")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIVE_STRATEGY_SCHEMA_VERSION,
            "entry_id": self.entry_id,
            "name": self.name,
            "author": self.author,
            "method": self.method,
            "regimes": list(self.regimes),
            "source_url": self.source_url,
            "source_name": self.source_name,
            "published_at": self.published_at,
            "collected_at": self.collected_at,
            "available_at": self.available_at,
            "summary": self.summary,
            "raw_excerpt": self.raw_excerpt,
            "extractor_version": self.extractor_version,
            "prompt_version": self.prompt_version,
            "meta": dict(self.meta),
        }

    def content_fingerprint(self) -> str:
        return fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExperienceEvent:
    """One simulated-execution outcome attributed to referenced strategies.

    ``outcome`` is binary (success/failure) for the reputation tally; a neutral
    outcome is recorded but does not change counts. ``strategy_ids`` links the
    event back to the exact strategies the subjective reading consulted.
    """

    event_id: str
    decision_id: str
    strategy_ids: tuple[str, ...]
    outcome: str
    recorded_at: str
    decision_time: str | None = None
    symbol: str | None = None
    realized_return: float | None = None
    note: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id must be non-empty")
        if not self.decision_id:
            raise ValueError("decision_id must be non-empty")
        if self.outcome not in ("success", "failure", "neutral"):
            raise ValueError("outcome must be success/failure/neutral")
        if not self.strategy_ids:
            raise ValueError("at least one strategy_id is required for attribution")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIVE_STRATEGY_SCHEMA_VERSION,
            "event_id": self.event_id,
            "decision_id": self.decision_id,
            "strategy_ids": list(self.strategy_ids),
            "outcome": self.outcome,
            "recorded_at": self.recorded_at,
            "decision_time": self.decision_time,
            "symbol": self.symbol,
            "realized_return": self.realized_return,
            "note": self.note,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True, slots=True)
class ProviderReport:
    """Explicit collector availability; failures are never silent zeros."""

    name: str
    available: bool
    reason: str | None = None
    collected: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "reason": self.reason,
            "collected": self.collected,
        }


__all__ = [
    "LIVE_STRATEGY_SCHEMA_VERSION",
    "StrategyEntry",
    "ExperienceEvent",
    "ProviderReport",
]
