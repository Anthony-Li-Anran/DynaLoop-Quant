"""Pane registry for backtest replay views.

The engine result remains a deterministic ledger. View panes are built here,
in Interaction, from two inputs only: the raw records Data returned (the tape)
and the engine's ordered timestamps. This keeps the engine untouched and lets
the view consume columns that the six-field ``Bar`` deliberately drops.

Only panes that can actually be drawn are returned. A column the source did
not provide produces no pane at all, so the view simply renders fewer panels;
it never explains what is absent. Every numeric column the source declares
gets a pane, including columns whose meaning was not identified (shown under
their source column name). Turnover value is never estimated from close x
volume: only a real ``amount`` column produces that pane.

Indicator math is delegated to bukosabino/ta (MIT), the reference library,
rather than reimplemented here:
  ta/trend.py::MACD, SMAIndicator -> EMA(12) - EMA(26); Signal = EMA(MACD, 9);
                                     Histogram = MACD - Signal; SMA(20)
  ta/momentum.py::RSIIndicator    -> Wilder RSI over 14 bars
  ta/utils.py::_ema               -> ewm(span=n, adjust=False, min_periods=0)
We pass ``fillna=True`` (min_periods=0) so short windows still render; values
before the reported ``warmup`` are not yet converged and the UI flags them.
Dependencies ``ta>=0.11`` and ``pandas>=2.0`` are declared in ``pyproject.toml``.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator

# Known extra columns get a curated financial label, unit and chart style.
# Any other numeric column is still published with a generic spec below.
RAW_PANE_SPECS: tuple[dict[str, str], ...] = (
    {"id": "volume", "column": "volume", "label": "Volume", "unit": "shares", "format": "integer", "style": "histogram"},
    {"id": "amount", "column": "amount", "label": "Traded Value", "unit": "CNY", "format": "currency", "style": "histogram"},
    {"id": "amplitude", "column": "amplitude", "label": "Amplitude", "unit": "%", "format": "decimal", "style": "line"},
    {"id": "change", "column": "change", "label": "Price Change", "unit": "CNY", "format": "decimal", "style": "line"},
    {"id": "change_pct", "column": "change_pct", "label": "Change", "unit": "%", "format": "decimal", "style": "line"},
    {"id": "turnover_rate", "column": "turnover_rate", "label": "Turnover Rate", "unit": "%", "format": "decimal", "style": "line"},
)

PRICE_FIELDS = frozenset(("date", "open", "high", "low", "close"))

SMA_WINDOW = 20
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
RSI_WINDOW = 14


def _timestamp_key(value: Any) -> str:
    """Comparable key for session dates and intraday timestamps alike.

    Right-padding keeps a short date and a full timestamp orderable without
    collapsing every bar of one session onto the same key:
    2024-01-02 -> 20240102000000, 2026-11-10 14:35 -> 20261110143500.
    """
    return re.sub(r"\D", "", str(value or "")).ljust(14, "0")


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _values(series: pd.Series) -> list[float | None]:
    return [_number(value) for value in series.tolist()]


def _column_label(name: str) -> str:
    words = re.sub(r"[_\-]+", " ", name).strip()
    if not words:
        return name
    return words[:1].upper() + words[1:]


def align_tape(
    rows: Sequence[Mapping[str, Any]], timestamps: Sequence[str]
) -> list[dict[str, Any]]:
    """Align raw source records to the engine's ordered timestamps."""
    by_timestamp: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _timestamp_key(row.get("date"))
        if key.strip("0"):
            by_timestamp[key] = dict(row)
    return [by_timestamp.get(_timestamp_key(timestamp), {}) for timestamp in timestamps]


def _pane(
    pane_id: str,
    label: str,
    unit: str,
    fmt: str,
    kind: str,
    placement: str,
    *,
    series: list[dict[str, Any]],
    definition: str | None = None,
    warmup: int = 0,
    reference_lines: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "id": pane_id,
        "label": label,
        "unit": unit,
        "format": fmt,
        "kind": kind,
        "placement": placement,
        "definition": definition,
        "warmup": warmup,
        "reference_lines": reference_lines or [],
        "series": series,
    }


def _raw_panes(
    tape: Sequence[Mapping[str, Any]], columns: Sequence[str]
) -> list[dict[str, Any]]:
    declared = [str(column) for column in columns]
    panes: list[dict[str, Any]] = []
    consumed: set[str] = set()

    for spec in RAW_PANE_SPECS:
        column = spec["column"]
        if column not in declared or not any(column in row for row in tape):
            continue
        values = [_number(row.get(column)) for row in tape]
        if not any(value is not None for value in values):
            continue
        panes.append(
            _pane(
                spec["id"],
                spec["label"],
                spec["unit"],
                spec["format"],
                "raw",
                "separate",
                series=[
                    {
                        "label": f"{spec['label']} ({spec['unit']})",
                        "style": spec["style"],
                        "values": values,
                    }
                ],
                definition=f"Raw source column '{column}'.",
            )
        )
        consumed.add(column)

    # A source may declare columns this registry has no curated spec for,
    # including the capability probe's column_N placeholders. They are real
    # values, so publish them under the source's own name instead of dropping
    # them. Non-numeric columns (notes, session labels) cannot be plotted.
    for column in declared:
        if column in consumed or column in PRICE_FIELDS:
            continue
        if not any(column in row for row in tape):
            continue
        values = [_number(row.get(column)) for row in tape]
        if sum(value is not None for value in values) < max(1, len(tape) // 2):
            continue
        label = _column_label(column)
        panes.append(
            _pane(
                column,
                label,
                "",
                "decimal",
                "raw",
                "separate",
                series=[{"label": label, "style": "line", "values": values}],
                definition=f"Raw source column '{column}'.",
            )
        )
    return panes


def _close_series(tape: Sequence[Mapping[str, Any]]) -> pd.Series:
    closes = [_number(row.get("close")) for row in tape]
    return pd.Series(
        [float(value) if value is not None else float("nan") for value in closes],
        dtype="float64",
    )


def _indicator_panes(
    tape: Sequence[Mapping[str, Any]], columns: Sequence[str]
) -> list[dict[str, Any]]:
    has_close = "close" in set(columns) and all(
        row.get("close") is not None for row in tape
    )
    if not has_close or not tape:
        return []

    close = _close_series(tape)
    sma = SMAIndicator(close=close, window=SMA_WINDOW, fillna=True).sma_indicator()
    macd_indicator = MACD(
        close=close,
        window_slow=MACD_SLOW,
        window_fast=MACD_FAST,
        window_sign=MACD_SIGNAL,
        fillna=True,
    )
    macd = macd_indicator.macd()
    signal = macd_indicator.macd_signal()
    histogram = macd_indicator.macd_diff()
    rsi = RSIIndicator(close=close, window=RSI_WINDOW, fillna=True).rsi()

    return [
        _pane(
            "sma_20",
            "Moving average",
            "CNY",
            "currency",
            "indicator",
            "overlay",
            series=[{"label": f"SMA ({SMA_WINDOW})", "style": "line", "values": _values(sma)}],
            definition=f"ta.trend.SMAIndicator: simple moving average of close over {SMA_WINDOW} bars.",
            warmup=SMA_WINDOW,
        ),
        _pane(
            "macd",
            "MACD",
            "index",
            "decimal",
            "indicator",
            "separate",
            series=[
                {"label": f"MACD ({MACD_FAST}, {MACD_SLOW})", "style": "line", "values": _values(macd)},
                {"label": f"Signal ({MACD_SIGNAL})", "style": "line", "values": _values(signal)},
                {"label": "Histogram", "style": "histogram", "values": _values(histogram)},
            ],
            definition=(
                f"ta.trend.MACD({MACD_FAST}, {MACD_SLOW}, {MACD_SIGNAL}): "
                "EMA(fast) - EMA(slow); Signal = EMA(MACD, sign); Histogram = MACD - Signal."
            ),
            warmup=MACD_SLOW + MACD_SIGNAL,
        ),
        _pane(
            "rsi_14",
            "RSI",
            "index",
            "decimal",
            "indicator",
            "separate",
            series=[{"label": f"RSI ({RSI_WINDOW})", "style": "line", "values": _values(rsi)}],
            definition=f"ta.momentum.RSIIndicator: Wilder RSI over {RSI_WINDOW} bars.",
            warmup=RSI_WINDOW,
            reference_lines=[30.0, 70.0],
        ),
    ]


def build_panes(
    rows: Sequence[Mapping[str, Any]],
    timestamps: Sequence[str],
    columns: Sequence[str],
) -> list[dict[str, Any]]:
    """Build every pane the source and indicator registry can actually draw."""
    tape = align_tape(rows, timestamps)
    return [*_raw_panes(tape, columns), *_indicator_panes(tape, columns)]


def default_view_config(panes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Every declared pane is shown; the user can hide any of them."""
    return {"visible_panes": [str(pane["id"]) for pane in panes]}


def normalise_view_config(
    panes: Sequence[Mapping[str, Any]], config: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Drop unknown ids so a saved view never refers to a pane that is absent."""
    known = {str(pane["id"]) for pane in panes}
    requested = (config or {}).get("visible_panes")
    if not isinstance(requested, list):
        return default_view_config(panes)
    visible = {str(pane_id) for pane_id in requested if str(pane_id) in known}
    order = {str(pane["id"]): index for index, pane in enumerate(panes)}
    return {"visible_panes": sorted(visible, key=lambda pane_id: order[pane_id])}
