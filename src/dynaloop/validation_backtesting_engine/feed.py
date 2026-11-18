"""Data feed and point-in-time view.

``StaticFeed.from_records`` is the caller-side adapter boundary: it turns
JSON-lines records (e.g. the Data module's A-share ``kline-json`` output) into
frames without importing any Data module types. The engine only sees an
ordered sequence of frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from dynaloop.validation_backtesting_engine.domain.models import (
    BacktestError,
    Bar,
    Frame,
)


@dataclass(frozen=True, slots=True)
class BarView:
    """Strategy-visible history: frames[0..current] only, never the future."""

    frames: tuple[Frame, ...]

    @property
    def timestamp(self) -> str:
        if not self.frames:
            raise BacktestError("BarView is empty.")
        return self.frames[-1].timestamp

    @property
    def current(self) -> Frame:
        if not self.frames:
            raise BacktestError("BarView is empty.")
        return self.frames[-1]

    def bar(self, symbol: str) -> Bar | None:
        return self.current.get(symbol)

    def symbols(self) -> tuple[str, ...]:
        observed: set[str] = set()
        for frame in self.frames:
            observed.update(frame.symbols())
        return tuple(sorted(observed))

    def history(self, symbol: str, length: int | None = None) -> tuple[Bar, ...]:
        bars = tuple(
            frame.bars[symbol] for frame in self.frames if symbol in frame.bars
        )
        return bars[-length:] if length is not None else bars

    def __len__(self) -> int:
        return len(self.frames)


class StaticFeed:
    """Ordered frames plus caller-supplied observational metadata."""

    def __init__(
        self,
        frames: Iterable[Frame],
        *,
        metadata: Mapping[str, Any] | None = None,
        timestamp_key: Callable[[str], Any] | None = None,
    ) -> None:
        self._key: Callable[[str], Any] = timestamp_key or (lambda value: value)
        self._frames = tuple(sorted(frames, key=lambda frame: self._key(frame.timestamp)))
        self._metadata: dict[str, Any] = dict(metadata or {})

    @property
    def frames(self) -> tuple[Frame, ...]:
        return self._frames

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def window(self, start: str | None = None, end: str | None = None) -> "StaticFeed":
        """A view over the frozen feed; no engine state is retained."""
        lower = self._key(start) if start not in (None, "") else None
        upper = self._key(end) if end not in (None, "") else None
        kept = tuple(
            frame
            for frame in self._frames
            if (lower is None or self._key(frame.timestamp) >= lower)
            and (upper is None or self._key(frame.timestamp) <= upper)
        )
        return StaticFeed(kept, metadata=self._metadata, timestamp_key=self._key)

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        symbol: str | None = None,
        timestamp_col: str = "date",
        open_col: str = "open",
        high_col: str = "high",
        low_col: str = "low",
        close_col: str = "close",
        volume_col: str = "volume",
        symbol_col: str | None = None,
        timestamp_key: Callable[[str], Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StaticFeed":
        """Build frames from JSON-lines records; column names are caller-settable.

        ``timestamp_key`` lets callers compare non-lexicographic timestamps
        (e.g. epoch strings). Without it the engine compares values as given and
        never assumes a frequency, calendar or timezone.
        """
        grouped: dict[str, dict[str, Bar]] = {}
        for position, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise BacktestError(f"Record {position} is not a mapping.")
            try:
                timestamp = str(record[timestamp_col])
                row_symbol = str(record[symbol_col]) if symbol_col else symbol
                if not row_symbol:
                    raise BacktestError("symbol is required when symbol_col is unset.")
                bar = Bar(
                    timestamp=timestamp,
                    symbol=row_symbol,
                    open=float(record[open_col]),
                    high=float(record[high_col]),
                    low=float(record[low_col]),
                    close=float(record[close_col]),
                    volume=float(record.get(volume_col, 0.0)),
                )
            except KeyError as exc:
                raise BacktestError(
                    f"Record {position} is missing column {exc.args[0]!r}."
                ) from exc
            except (TypeError, ValueError) as exc:
                raise BacktestError(f"Record {position} has an invalid value: {exc}") from exc
            bars = grouped.setdefault(timestamp, {})
            if row_symbol in bars:
                raise BacktestError(
                    f"Duplicate bar for {row_symbol!r} at {timestamp!r}."
                )
            bars[row_symbol] = bar
        frames = tuple(
            Frame(timestamp=timestamp, bars=dict(bars))
            for timestamp, bars in grouped.items()
        )
        feed_metadata: dict[str, Any] = dict(metadata or {})
        feed_metadata.setdefault("timestamp_col", timestamp_col)
        return cls(frames, metadata=feed_metadata, timestamp_key=timestamp_key)
