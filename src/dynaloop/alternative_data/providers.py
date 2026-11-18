"""Pluggable providers for the shared alternative-data layer.

Every provider is optional and network access is best-effort. A provider that
cannot fetch returns an explicit :class:`ProviderStatus` with
``available=False`` and an empty result -- it never fabricates rows, never
silently substitutes zeros, and never raises into the decision path.

The layer exposes a point-in-time alignment helper so downstream branches see
only records whose ``available_at`` is not after the decision timestamp.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from dynaloop.alternative_data.contracts import NewsRecord, ProviderStatus


@runtime_checkable
class NewsProvider(Protocol):
    """A source of point-in-time-tagged news records."""

    @property
    def name(self) -> str: ...

    def status(self) -> ProviderStatus:
        """Report capability without side effects."""
        ...

    def fetch(self, *, symbols: Sequence[str] = (), limit: int = 50) -> list[NewsRecord]:
        """Return records; empty list when unavailable. Must not fabricate."""
        ...


class NullNewsProvider:
    """The default, always-unavailable provider.

    Used when no real source is configured or a source is down. Returning an
    explicit ``unavailable`` status keeps the absence visible instead of faking
    an empty-but-healthy feed.
    """

    def __init__(self, reason: str = "no real news provider configured") -> None:
        self._reason = reason

    @property
    def name(self) -> str:
        return "null"

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, available=False, reason=self._reason)

    def fetch(self, *, symbols: Sequence[str] = (), limit: int = 50) -> list[NewsRecord]:
        return []


class StaticNewsProvider:
    """In-memory records supplied by a caller (e.g. a replay fixture).

    Records are used as-is; the caller is responsible for truthful timestamps.
    """

    def __init__(self, records: Sequence[NewsRecord], reason: str | None = None) -> None:
        self._records = tuple(records)

    @property
    def name(self) -> str:
        return "static"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            available=bool(self._records),
            reason=None if self._records else (reason or "no records supplied"),
            record_count=len(self._records),
        )

    def fetch(self, *, symbols: Sequence[str] = (), limit: int = 50) -> list[NewsRecord]:
        selected = list(self._records[:limit])
        if symbols:
            wanted = set(symbols)
            selected = [r for r in selected if not r.symbols or wanted & set(r.symbols)]
        return selected


def align_to_available_time(
    records: Sequence[NewsRecord], decision_time: str
) -> list[NewsRecord]:
    """Keep only records whose result was already available at decision time.

    String comparison is valid for ISO-8601-like timestamps (``YYYY-MM-DD`` or
    ``YYYY-MM-DDTHH:MM:SS``) which all providers must emit. Records with an
    ``available_at`` strictly after ``decision_time`` are excluded: using them
    would be contract-visible look-ahead.
    """
    return [r for r in records if r.available_at and r.available_at <= decision_time]


__all__ = [
    "NewsProvider",
    "NullNewsProvider",
    "StaticNewsProvider",
    "align_to_available_time",
]
