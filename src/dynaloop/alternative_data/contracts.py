"""Point-in-time data contracts for the shared alternative-data layer.

Both the subjective (LLM) branch and the quantitative branch consume these
records. The single most important rule: a record may only enter a decision at
or after ``available_at`` -- the moment its result genuinely became usable --
never at ``published_at`` (the original event time) or ``fetched_at`` (when the
collector happened to pull it). This is the alignment discipline required by
``docs/brain.md``.

No record here is a factor, a signal verdict, or an investment claim. Missing
data stays missing (``available=False``); nothing is back-filled or invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NewsRecord:
    """One external news / announcement item with full time provenance."""

    headline: str
    source: str
    published_at: str | None
    fetched_at: str
    available_at: str
    symbols: tuple[str, ...] = ()
    model_version: str | None = None      # set when a model produced/transformed it
    prompt_version: str | None = None     # set when a prompt produced/transformed it
    raw_excerpt: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.headline:
            raise ValueError("headline must be non-empty")
        if not self.available_at:
            raise ValueError("available_at is mandatory for point-in-time alignment")

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "source": self.source,
            "published_at": self.published_at,
            "fetched_at": self.fetched_at,
            "available_at": self.available_at,
            "symbols": list(self.symbols),
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "raw_excerpt": self.raw_excerpt,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True, slots=True)
class SentimentRecord:
    """A dated sentiment reading for a symbol or the whole market.

    ``scope`` is "market" or a symbol code. ``score`` is a bounded, auditable
    number from a rule-based engine; it is report-only, never a verdict.
    """

    date: str
    scope: str
    score: float
    scale_min: float
    scale_max: float
    source: str
    available_at: str
    available: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "scope": self.scope,
            "score": self.score,
            "scale_min": self.scale_min,
            "scale_max": self.scale_max,
            "source": self.source,
            "available_at": self.available_at,
            "available": self.available,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """Explicit capability/availability report; never silently returns zero."""

    name: str
    available: bool
    reason: str | None = None
    record_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "reason": self.reason,
            "record_count": self.record_count,
        }
