"""Assemble the subjective-analysis input context from the shared data layer.

This module prepares a structured, point-in-time-correct context object that the
front end passes to the WorkBuddy LLM interface. It does NOT call any model and
produces NO verdict. Four input families are included:

1. A-share market data (via the configured data facade, summary only)
2. News (via a pluggable NewsProvider; best-effort, explicit unavailable)
3. Sentiment (the rule-based cycle snapshot, if supplied; report-only)
4. Strategy library (read-only candidate metadata, no return claims)

Every external feed is best-effort. Missing sources are surfaced as
``available=False`` with a reason, never filled with fabricated rows.
"""

from __future__ import annotations

from typing import Any

from dynaloop.alternative_data.contracts import ProviderStatus
from dynaloop.alternative_data.providers import (
    NewsProvider,
    NullNewsProvider,
    align_to_available_time,
)
from dynaloop.alternative_data.strategy_library import list_candidates


def build_subjective_input(
    *,
    decision_time: str,
    symbols: tuple[str, ...] = (),
    news_provider: NewsProvider | None = None,
    sentiment_snapshot: dict[str, Any] | None = None,
    a_share_summary: dict[str, Any] | None = None,
    live_strategies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a report-only context snapshot for subjective LLM analysis.

    ``decision_time`` is the as-of timestamp. News is admitted only when its
    ``available_at`` is not after this time (point-in-time alignment).
    """
    provider = news_provider or NullNewsProvider()
    status: ProviderStatus = provider.status()
    raw = provider.fetch(symbols=symbols, limit=50) if status.available else []
    admitted = align_to_available_time(raw, decision_time)

    return {
        "schema": "subjective-input/1",
        "decision_time": decision_time,
        "not_a_claim": "context for subjective analysis only; no effectiveness or return claim",
        "inputs": {
            "a_share_data": {
                "available": a_share_summary is not None,
                "data": a_share_summary,
                "reason": None if a_share_summary is not None else "no market summary supplied",
            },
            "news": {
                "provider": status.to_dict(),
                "records": [r.to_dict() for r in admitted],
                "count": len(admitted),
            },
            "sentiment": {
                "available": sentiment_snapshot is not None,
                "data": sentiment_snapshot,
                "reason": None if sentiment_snapshot is not None else "no sentiment snapshot supplied",
            },
            "strategy_library": {
                "available": True,
                "source": "living_library" if live_strategies is not None else "static_registry",
                "candidates": live_strategies if live_strategies is not None else list_candidates(),
            },
        },
    }


__all__ = ["build_subjective_input"]
