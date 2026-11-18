"""Explicitly labelled synthetic demo bars for a reproducible one-command run.

These are NOT market data. They exist so the whole six-stage loop can be
executed without network access and compared byte-for-byte. Real runs inject
frozen bar records from ``FactorResearch.fetch_records`` or a JSON snapshot.
"""

from __future__ import annotations

from typing import Any


def synthetic_demo_records(count: int = 40) -> list[dict[str, Any]]:
    """Deterministic OHLCV rows; the source label is always explicit."""
    if count < 10:
        raise ValueError("count must be at least 10 for the default windows.")
    rows: list[dict[str, Any]] = []
    for index in range(count):
        if index < 31:
            day = f"2024-01-{index + 1:02d}"
        else:
            day = f"2024-02-{index - 30:02d}"
        close = 10.0 + (index % 5) * 0.2 + index * 0.05
        rows.append(
            {
                "date": day,
                "open": 10.0 + index * 0.1,
                "high": 10.6 + index * 0.1,
                "low": 9.4 + index * 0.1,
                "close": close,
                "volume": 1000 + index * 10,
            }
        )
    return rows


SYNTHETIC_SOURCE_METADATA: dict[str, Any] = {
    "synthetic_demo": True,
    "provenance": "dynaloop.orchestrator.samples.synthetic_demo_records",
    "note": "not market data; inject real frozen records for research runs",
}
