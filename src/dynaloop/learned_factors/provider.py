"""Local reader for the Qlib-style binary archive.

This module deliberately does NOT import qlib. It reproduces the small part of
``qlib.data.data.CalendarProvider`` / ``InstrumentProvider`` / ``FeatureProvider``
that a factor workflow needs, so every layer stays replaceable later.

Binary layout (per instrument, per field): one ``float32`` start index followed
by ``float32`` values aligned to the trading calendar.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import tarfile
from typing import Iterable

import numpy as np
import pandas as pd

# Alpha158 only needs these six base fields; the archive has four more.
BASE_FIELDS = ("open", "high", "low", "close", "volume", "vwap")
ALL_FIELDS = (
    "open", "high", "low", "close", "volume", "vwap",
    "amount", "adjclose", "change", "factor",
)


class ArchiveError(ValueError):
    """Raised when the archive does not match its release manifest."""


def decode_feature(payload: bytes, size: int) -> np.ndarray:
    """Decode one ``*.day.bin`` payload into a calendar-aligned float array."""
    values = np.frombuffer(payload, dtype="<f4")
    if len(values) < 2 or not np.isfinite(values[0]):
        raise ArchiveError("invalid Qlib feature header")
    start = int(values[0])
    end = start + len(values) - 1
    if values[0] != start or not 0 <= start < end <= size:
        raise ArchiveError("feature exceeds the trading calendar")
    out = np.full(size, np.nan, dtype=np.float64)
    out[start:end] = values[1:]
    out[np.isinf(out)] = np.nan
    return out


@dataclass(frozen=True, slots=True)
class ArchiveDigest:
    archive_size_bytes: int
    archive_sha256: str
    target_trade_date: str
    calendar_size: int
    instrument_rows: int
    symbols: int


class QlibBinaryProvider:
    """Read-only, manifest-verified provider for a Qlib binary archive.

    Parameters
    ----------
    archive, manifest:
        Paths to ``*.tar.gz`` and its release manifest.
    universe:
        Name of an ``instruments/*.txt`` file, e.g. ``csi300``.
    fields:
        Base fields to materialise. Defaults to the six Alpha158 inputs.
    """

    def __init__(
        self,
        archive: Path | str,
        manifest: Path | str,
        *,
        universe: str = "csi300",
        fields: Iterable[str] = BASE_FIELDS,
    ) -> None:
        self.archive = Path(archive)
        self.manifest_path = Path(manifest)
        self.universe = universe
        self.fields = tuple(dict.fromkeys(fields))
        unknown = set(self.fields) - set(ALL_FIELDS)
        if unknown:
            raise ArchiveError(f"unknown base fields: {sorted(unknown)}")
        self._meta = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self._verify_archive()
        self.calendar, self.membership, self.frames, self.digest = self._load()

    def _verify_archive(self) -> None:
        with self.archive.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if self.archive.stat().st_size != self._meta["archive_size_bytes"]:
            raise ArchiveError("archive size differs from the release manifest")
        if f"sha256:{digest}" != self._meta["archive_sha256"]:
            raise ArchiveError("archive checksum differs from the release manifest")

    def _load(self):
        with tarfile.open(self.archive, "r:gz") as tar:
            calendar = pd.DatetimeIndex(
                pd.to_datetime(
                    tar.extractfile("qlib_bin/calendars/day.txt").read().decode().split()
                )
            )
            if not calendar.is_monotonic_increasing or not calendar.is_unique:
                raise ArchiveError("invalid trading calendar")
            if calendar[-1].date().isoformat() != self._meta["target_trade_date"]:
                raise ArchiveError("calendar end differs from the release manifest")

            instrument_path = f"qlib_bin/instruments/{self.universe}.txt"
            lines = tar.extractfile(instrument_path).read().decode().splitlines()
            membership: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = defaultdict(list)
            for line in lines:
                parts = line.split()
                if len(parts) != 3:
                    raise ArchiveError(f"invalid instrument row: {line}")
                symbol, start, end = parts[0].lower(), pd.Timestamp(parts[1]), pd.Timestamp(parts[2])
                if start > end:
                    raise ArchiveError(f"invalid membership interval: {line}")
                membership[symbol].append((start, end))

            # One sequential pass over the archive. Streaming avoids holding the
            # whole 571 MB compressed member table in memory at once.
            wanted = {f"{field}.day.bin" for field in self.fields}
            raw: dict[str, dict[str, np.ndarray]] = defaultdict(dict)
            with tarfile.open(self.archive, "r|gz") as stream:
                for entry in stream:
                    parts = entry.name.split("/")
                    if len(parts) != 4 or parts[:2] != ["qlib_bin", "features"]:
                        continue
                    symbol, filename = parts[2], parts[3]
                    if symbol not in membership or filename not in wanted:
                        continue
                    payload = stream.extractfile(entry).read()
                    raw[symbol][filename] = decode_feature(payload, len(calendar))

        frames: dict[str, pd.DataFrame] = {}
        for symbol, columns in raw.items():
            if set(columns) != wanted:
                # A partially available instrument is kept only when all
                # requested base fields exist; never synthesise missing data.
                continue
            frames[symbol] = pd.DataFrame(
                {field: columns[f"{field}.day.bin"] for field in self.fields},
                index=calendar,
                dtype=np.float64,
            )
        if not frames:
            raise ArchiveError("no instrument with a complete base-field set")

        meta = ArchiveDigest(
            archive_size_bytes=int(self._meta["archive_size_bytes"]),
            archive_sha256=str(self._meta["archive_sha256"]),
            target_trade_date=str(self._meta["target_trade_date"]),
            calendar_size=len(calendar),
            instrument_rows=len(lines),
            symbols=len(frames),
        )
        return calendar, dict(membership), frames, meta

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.frames))

    def frame(self, symbol: str) -> pd.DataFrame:
        return self.frames[symbol.lower()]

    def membership_mask(self, symbol: str) -> np.ndarray:
        """Point-in-time-ish availability mask from historical intervals."""
        mask = np.zeros(len(self.calendar), dtype=bool)
        for start, end in self.membership.get(symbol.lower(), ()):
            left = int(np.searchsorted(self.calendar, start, side="left"))
            right = int(np.searchsorted(self.calendar, end, side="right"))
            mask[left:right] = True
        return mask

    def provenance(self) -> dict[str, object]:
        return {
            "archive": self.archive.name,
            "manifest": self.manifest_path.name,
            "universe": self.universe,
            "fields": list(self.fields),
            "calendar": [self.calendar[0].date().isoformat(),
                         self.calendar[-1].date().isoformat()],
            "calendar_size": self.digest.calendar_size,
            "symbols": self.digest.symbols,
            "membership_basis": "approximate",
            "survivorship_bias": "NOT eliminated; historical membership intervals only",
            "digest": {
                "archive_size_bytes": self.digest.archive_size_bytes,
                "archive_sha256": self.digest.archive_sha256,
                "target_trade_date": self.digest.target_trade_date,
            },
        }
