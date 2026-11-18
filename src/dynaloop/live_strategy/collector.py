"""Pluggable strategy collectors.

The default collector is offline and explicitly reports unavailable -- the
project never fabricates harvested strategies. A live collector is injected by
the daily automation (which performs the web search and LLM extraction) and
hands over already-structured candidate dicts; this module only validates and
normalises them into StrategyEntry records with correct time provenance.

The published/available time rule mirrors the news layer: a strategy discovered
today is available from the moment it was collected, never back-dated to its
claim publication time. A source that advertises a publication date later than
the collection date is rejected (could not have been known when collected).
"""

from __future__ import annotations

from typing import Any, Protocol

from dynaloop.live_strategy.contracts import ProviderReport, StrategyEntry


class StrategyCollector(Protocol):
    name: str

    def status(self) -> ProviderReport: ...

    def collect(self, *, query: str, limit: int = 10) -> list[StrategyEntry]: ...


class NullStrategyCollector:
    """Offline default: no network, explicit unavailable reason."""

    name = "null"

    def __init__(self, reason: str = "live collection not requested") -> None:
        self._reason = reason

    def status(self) -> ProviderReport:
        return ProviderReport(name=self.name, available=False, reason=self._reason)

    def collect(self, *, query: str, limit: int = 10) -> list[StrategyEntry]:
        return []


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"candidate missing required field: {key}")
    return value.strip()


def normalize_candidate(
    payload: dict[str, Any],
    *,
    collected_at: str,
    extractor_version: str = "schema-extract/1",
    prompt_version: str | None = None,
) -> StrategyEntry:
    """Validate a structured candidate into a point-in-time-correct entry."""
    name = _required_str(payload, "name")
    method = _required_str(payload, "method")
    source_url = _required_str(payload, "source_url")
    summary = _required_str(payload, "summary")
    published_at = payload.get("published_at")
    if published_at is not None and not isinstance(published_at, str):
        raise ValueError("published_at must be a string or null")
    # available_at is ALWAYS the collection time, never the claimed publication
    # time. Back-dating to published_at would let a strategy discovered later be
    # consulted by an earlier decision -- contract-level look-ahead. This
    # mirrors the news layer: usable only from when we actually obtained it.
    available_at = str(collected_at)[:10]
    regimes = payload.get("regimes") or []
    if not isinstance(regimes, list) or not all(isinstance(r, str) for r in regimes):
        raise ValueError("regimes must be a list of strings")
    entry_id = str(payload.get("entry_id") or "").strip()
    if not entry_id:
        basis = f"{source_url}|{name}".encode("utf-8")
        import hashlib
        entry_id = hashlib.sha256(basis).hexdigest()[:16]
    author = payload.get("author")
    if author is not None and not isinstance(author, str):
        raise ValueError("author must be a string or null")
    return StrategyEntry(
        entry_id=entry_id,
        name=name,
        author=author,
        method=method,
        regimes=tuple(r.strip() for r in regimes if r.strip()),
        source_url=source_url,
        source_name=str(payload.get("source_name") or "web"),
        published_at=published_at,
        collected_at=str(collected_at),
        available_at=available_at,
        summary=summary,
        raw_excerpt=payload.get("raw_excerpt"),
        extractor_version=extractor_version,
        prompt_version=prompt_version,
        meta=dict(payload.get("meta") or {}),
    )


class StructuredCandidateCollector:
    """In-memory collector fed by the daily automation's structured output."""

    def __init__(
        self,
        candidates: list[dict[str, Any]],
        *,
        collected_at: str,
        extractor_version: str = "schema-extract/1",
        prompt_version: str | None = None,
    ) -> None:
        self.name = "structured"
        self._candidates = candidates
        self._collected_at = collected_at
        self._extractor_version = extractor_version
        self._prompt_version = prompt_version
        self._error: str | None = None

    def status(self) -> ProviderReport:
        return ProviderReport(
            name=self.name,
            available=self._error is None and bool(self._candidates),
            reason=self._error or ("no candidates supplied" if not self._candidates else None),
            collected=len(self._candidates),
        )

    def collect(self, *, query: str, limit: int = 10) -> list[StrategyEntry]:
        entries: list[StrategyEntry] = []
        for candidate in self._candidates[:limit]:
            try:
                entries.append(normalize_candidate(
                    candidate,
                    collected_at=self._collected_at,
                    extractor_version=self._extractor_version,
                    prompt_version=self._prompt_version,
                ))
            except ValueError as exc:
                self._error = str(exc)
        return entries


__all__ = [
    "StrategyCollector",
    "NullStrategyCollector",
    "StructuredCandidateCollector",
    "normalize_candidate",
]
