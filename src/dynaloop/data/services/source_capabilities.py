"""Automatic capability discovery for registered data sources.

A source saved in Data becomes backtest-ready with no adapter code. Data fetches
one sample response, infers the tabular layout and the meaning of each column,
then persists a capability declaration keyed by the source key. Backtest runs
read that declaration instead of any per-source branching.

The declaration is honest by construction: columns the source did not return
are reported as missing, and columns whose meaning was guessed (because the
payload has no header) are flagged as inferred.
"""

from __future__ import annotations

from dynaloop.infrastructure import JsonMappingStore

import csv
import hashlib
import io
import json
import math
import os
import re
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dynaloop.data.domain.errors import DataDefinitionError
from dynaloop.data.domain.models import AcquisitionMode, FetchRequest
from dynaloop.data.services.api_source import (
    ApiSourceConfig,
    ConfiguredHttpAdapter,
    ConfiguredLocalAdapter,
)

STANDARD_FIELDS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
REQUIRED_FIELDS: tuple[str, ...] = ("date", "open", "high", "low", "close")

# Bumped whenever the inference rules change, so cached declarations from an
# older build are re-probed automatically instead of staying stale forever.
CAPABILITY_SCHEMA_VERSION = 4

ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "datetime", "timestamp", "time", "trade_date", "tradedate", "day"),
    "open": ("open", "openprice", "o"),
    "high": ("high", "highprice", "h"),
    "low": ("low", "lowprice", "l"),
    "close": ("close", "closeprice", "c", "last", "price"),
    "volume": ("volume", "vol", "v", "qty", "quantity"),
    "amount": ("amount", "turnover", "money", "value", "amt", "turnover_value"),
    "amplitude": ("amplitude",),
    "change": ("change",),
    "change_pct": ("change_pct", "pct_chg", "change_percent", "chg_pct"),
    "turnover_rate": ("turnover_rate", "turn", "turnover_ratio"),
}

_TIMESTAMP_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}|\d{8}|\d{10,14})(?:[ T].*)?$"
)
_SYMBOL_RE = re.compile(r"^(?:(?:sh|sz|bj)\d{6}|\d\.\d{6}|\d{6}(?:\.(?:SH|SZ))?)$", re.I)
_DATE_DASH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_COMPACT_RE = re.compile(r"^\d{8}$")
_FREQUENCY_WORDS = frozenset(("day", "week", "month", "daily", "weekly", "monthly"))
_ADJUST_WORDS = frozenset(("qfq", "hfq"))
_LIMIT_KEYS = frozenset(("lmt", "limit", "count", "num", "size", "rows", "datalen"))
# K-line endpoints that expose a "most recent N bars" parameter almost always
# call it lmt. It is injected only for intraday requests when the source did not
# declare its own limit parameter; the value is a generic convention, not a
# vendor-specific rule keyed on a source name.
_DEFAULT_LIMIT_KEY = "lmt"
MINUTES_PER_SESSION = 240

# Frequency is a capability a source declares, never a global day/week/month
# enum. Canonical ids are the only vocabulary the backtest layer knows; how a
# source spells them is derived from the shape of the value it saved.
PERIODS: tuple[dict[str, Any], ...] = (
    {"value": "1m", "label": "1 minute", "minutes": 1, "numeric": "1", "mk": "m1", "word": ""},
    {"value": "5m", "label": "5 minutes", "minutes": 5, "numeric": "5", "mk": "m5", "word": ""},
    {"value": "15m", "label": "15 minutes", "minutes": 15, "numeric": "15", "mk": "m15", "word": ""},
    {"value": "30m", "label": "30 minutes", "minutes": 30, "numeric": "30", "mk": "m30", "word": ""},
    {"value": "60m", "label": "Hourly", "minutes": 60, "numeric": "60", "mk": "m60", "word": ""},
    {"value": "1d", "label": "Daily", "minutes": 1440, "numeric": "101", "mk": "", "word": "day"},
    {"value": "1w", "label": "Weekly", "minutes": 10080, "numeric": "102", "mk": "", "word": "week"},
    {"value": "1M", "label": "Monthly", "minutes": 43200, "numeric": "103", "mk": "", "word": "month"},
)
PERIOD_BY_VALUE: dict[str, dict[str, Any]] = {item["value"]: item for item in PERIODS}
PERIOD_OPTIONS: list[dict[str, str]] = [
    {"value": item["value"], "label": item["label"]} for item in PERIODS
]
_WORD_FORMS = frozenset(
    ("day", "daily", "week", "weekly", "month", "monthly")
)
_PERIOD_ALIASES: dict[str, str] = {
    "1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m",
    "60min": "60m", "1h": "60m", "hour": "60m", "hourly": "60m",
    "d": "1d", "1d": "1d", "day": "1d", "daily": "1d",
    "w": "1w", "1w": "1w", "week": "1w", "weekly": "1w",
    "1mo": "1M", "month": "1M", "monthly": "1M",
}


def period_minutes(period: str) -> int:
    """Trading minutes per bar; used only for observation metadata and limits."""
    return int(PERIOD_BY_VALUE.get(period, {}).get("minutes", 1440))


def is_intraday(period: str) -> bool:
    """Whether a period carries an intraday timestamp (not a session date)."""
    return period_minutes(period) < 1440


def decode_frequency(template: str) -> str | None:
    """Map a source's saved frequency value onto a canonical period id."""
    value = str(template or "").strip()
    folded = value.casefold()
    if value in PERIOD_BY_VALUE:
        return value
    if folded in _PERIOD_ALIASES:
        return _PERIOD_ALIASES[folded]
    if re.fullmatch(r"m\d+", folded):
        minutes = folded[1:]
        return f"{minutes}m" if f"{minutes}m" in PERIOD_BY_VALUE else None
    if value.isdigit():
        for item in PERIODS:
            if item["numeric"] == value:
                return item["value"]
    for item in PERIODS:
        if item["word"] and folded in (item["word"], f"{item['word']}ly"):
            return item["value"]
    return None


def encode_frequency(template: str, period: str) -> str | None:
    """Spell a canonical period the way this source's saved value is shaped."""
    item = PERIOD_BY_VALUE.get(period)
    if item is None:
        return None
    value = str(template or "").strip()
    folded = value.casefold()
    if value.isdigit() and item["numeric"]:
        return str(item["numeric"])
    if re.fullmatch(r"m\d+", folded) and item["mk"]:
        return str(item["mk"])
    if folded in _WORD_FORMS and item["word"]:
        return str(item["word"])
    if value in PERIOD_BY_VALUE or folded in _PERIOD_ALIASES:
        return period
    return None


def frequency_options(template: str) -> list[dict[str, str]]:
    """Periods this source can actually express, derived from its own value."""
    value = str(template or "").strip()
    folded = value.casefold()
    if not value:
        return []  # the source has no frequency parameter at all
    if value.isdigit():
        return [dict(opt) for opt in PERIOD_OPTIONS if PERIOD_BY_VALUE[opt["value"]]["numeric"]]
    if re.fullmatch(r"m\d+", folded):
        return [dict(opt) for opt in PERIOD_OPTIONS if PERIOD_BY_VALUE[opt["value"]]["mk"]]
    if folded in _WORD_FORMS:
        return [dict(opt) for opt in PERIOD_OPTIONS if PERIOD_BY_VALUE[opt["value"]]["word"]]
    # Unknown shape: the caller may still pass any value straight through.
    return [dict(opt) for opt in PERIOD_OPTIONS]


def frequency_template(bindings: Mapping[str, Any]) -> str:
    """Find the saved value of the parameter bound to the frequency role."""
    slots = bindings.get("slots") or {}
    templates = bindings.get("templates") or {}
    if bindings.get("kind") == "csv":
        for template, role in zip(list(templates), list(slots)):
            if role == "frequency":
                return str(template)
        return ""
    for key, role in dict(slots).items():
        if role == "frequency":
            return str(dict(templates).get(key, ""))
    return ""


def time_key(value: Any) -> str:
    """Comparable key for dates, datetimes and compact intraday stamps.

    Short keys are right-padded so a plain session date and a full timestamp
    remain orderable: 2024-01-02 -> 20240102000000, 2026-11-10 14:35 ->
    20261110143500. Nothing here interprets the unit of the timestamp.
    """
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.ljust(14, "0")


def source_signature(config: ApiSourceConfig) -> str:
    """Fingerprint the parts of a source config that affect probing."""
    payload = {
        "key": config.key,
        "url": config.url,
        "method": config.method,
        "query": dict(config.query),
        "headers": dict(config.headers),
        "kind": config.kind,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class SourceCapabilityStore:
    """JSON-file cache of probed capabilities, keyed by source key."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._store = JsonMappingStore(path, error_type=DataDefinitionError, label='Source capability cache', recover_invalid=True)

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, dict[str, Any]]:
        return self._store.read()

    def get(self, key: str) -> dict[str, Any] | None:
        return self._read().get(key)

    def save(self, key: str, capability: Mapping[str, Any]) -> dict[str, Any]:
        with self._store.transaction() as entries:
            entry = dict(capability)
            entry["source_key"] = key
            entries[key] = entry
        return entry

    def delete(self, key: str) -> None:
        with self._store.transaction() as entries:
            entries.pop(key, None)


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _looks_like_timestamp(value: str) -> bool:
    return bool(_TIMESTAMP_RE.match(value.strip()))


def _split_row(row: Any) -> list[str] | None:
    if isinstance(row, (list, tuple)):
        return ["" if item is None else str(item) for item in row]
    if isinstance(row, str):
        return [part.strip() for part in row.split(",")]
    return None


def _first_cell(row: Any) -> str:
    if isinstance(row, Mapping):
        for key in ("date", "datetime", "timestamp", "time", "trade_date", "day"):
            if key in row:
                return str(row[key])
        return str(next(iter(row.values()))) if row else ""
    parts = _split_row(row)
    return parts[0] if parts else ""


def _row_width(row: Any) -> int:
    if isinstance(row, Mapping):
        return len(row)
    parts = _split_row(row)
    return len(parts) if parts else 0


def _find_rows(node: Any, path: tuple[str, ...] = ()) -> tuple[list[Any], tuple[str, ...]]:
    """Locate the widest timestamp-led table inside a decoded JSON payload."""
    best: tuple[int, list[Any], tuple[str, ...]] = (0, [], ())

    def walk(current: Any, current_path: tuple[str, ...]) -> None:
        nonlocal best
        if isinstance(current, list):
            if len(current) >= 2 and all(
                _looks_like_timestamp(_first_cell(row)) for row in current[:3]
            ):
                width = max((_row_width(row) for row in current[:3]), default=0)
                score = len(current) * max(width, 1)
                if score > best[0]:
                    best = (score, current, current_path)
            return
        if isinstance(current, Mapping):
            for key, value in current.items():
                walk(value, current_path + (str(key),))

    walk(node, path)
    if not best[1]:
        raise DataDefinitionError(
            "No timestamp-led row series found in the source response; "
            "this source cannot supply bar records."
        )
    return best[1], best[2]


def _decode_table(raw: bytes) -> tuple[list[str], list[list[str]], dict[str, Any]]:
    """Decode one response into (headers, string rows, layout descriptor)."""
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise DataDefinitionError("The source returned an empty response.")

    payload: Any = None
    if text[0] in "[{":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None

    if payload is not None:
        rows, path = _find_rows(payload)
        layout: dict[str, Any] = {"kind": "json", "path": list(path)}
        if isinstance(rows[0], Mapping):
            headers = [
                str(key) for key in dict.fromkeys(
                    key for row in rows[:20] if isinstance(row, Mapping) for key in row
                )
            ]
            layout["row_kind"] = "object"
            matrix = [
                ["" if row.get(key) is None else str(row.get(key)) for key in headers]
                if isinstance(row, Mapping) else []
                for row in rows
            ]
            layout["explicit"] = True
        else:
            first = _split_row(rows[0]) or []
            headers = [f"column_{index + 1}" for index in range(len(first))]
            matrix = [_split_row(row) or [] for row in rows]
            layout["row_kind"] = "csv" if isinstance(rows[0], str) else "array"
            layout["explicit"] = False
        return headers, matrix, layout

    lines = [line for line in text.splitlines() if line.strip()]
    if lines and lines[0].lstrip().startswith("{"):
        try:
            objects = [json.loads(line) for line in lines]
            headers = [
                str(key) for key in dict.fromkeys(
                    key for obj in objects if isinstance(obj, Mapping) for key in obj
                )
            ]
            matrix = [
                ["" if obj.get(key) is None else str(obj.get(key)) for key in headers]
                for obj in objects
                if isinstance(obj, Mapping)
            ]
            return headers, matrix, {
                "kind": "jsonl",
                "path": [],
                "row_kind": "object",
                "explicit": True,
            }
        except json.JSONDecodeError as exc:
            raise DataDefinitionError("The source response is not valid JSON-lines.") from exc

    reader = list(csv.reader(io.StringIO(text)))
    if not reader:
        raise DataDefinitionError("The source response is not a table.")
    first = reader[0]
    explicit = not _looks_like_timestamp(first[0]) if first else False
    headers = [str(cell).strip() for cell in first] if explicit else [
        f"column_{index + 1}" for index in range(len(first))
    ]
    matrix = reader[1:] if explicit else reader
    return headers, matrix, {
        "kind": "csv",
        "path": [],
        "row_kind": "array",
        "explicit": explicit,
    }


def _match_alias(name: str) -> str | None:
    folded = re.sub(r"[^a-z0-9]", "", name.casefold())
    for semantic, aliases in ALIASES.items():
        if folded in aliases:
            return semantic
    for semantic, aliases in ALIASES.items():
        if any(alias in folded for alias in aliases if len(alias) >= 4):
            return semantic
    return None


def _positional_map(matrix: Sequence[Sequence[str]]) -> dict[str, int] | None:
    """Infer OHLCV positions from the numeric relations inside each row."""
    sample = matrix[:50]
    if not sample or not _looks_like_timestamp(sample[0][0]):
        return None
    high_votes: Counter[int] = Counter()
    low_votes: Counter[int] = Counter()
    for row in sample:
        if len(row) < 5:
            continue
        values = [_to_float(cell) for cell in row[1:5]]
        if any(value is None for value in values):
            continue
        numbers = [float(value) for value in values if value is not None]
        high_votes[numbers.index(max(numbers))] += 1
        low_votes[numbers.index(min(numbers))] += 1
    if not high_votes or not low_votes:
        return None
    high = high_votes.most_common(1)[0][0]
    low = low_votes.most_common(1)[0][0]
    if high == low:
        return None
    rest = [index for index in range(4) if index not in (high, low)]
    if len(rest) != 2:
        return None
    mapping: dict[str, int] = {
        "date": 0,
        "open": 1 + rest[0],
        "close": 1 + rest[1],
        "high": 1 + high,
        "low": 1 + low,
        "volume": 5,
    }
    return mapping if len(sample[0]) >= 6 else None


def _infer_amount_index(
    matrix: Sequence[Sequence[str]], field_map: Mapping[str, int], start: int
) -> int | None:
    """A headerless extra column of the same order as volume x price is turnover."""
    volume_index = field_map.get("volume")
    close_index = field_map.get("close")
    if volume_index is None or close_index is None:
        return None
    for index in range(start, min(start + 8, len(matrix[0]) if matrix else start)):
        ratios: list[float] = []
        for row in matrix[:50]:
            if len(row) <= max(index, volume_index, close_index):
                continue
            volume = _to_float(row[volume_index])
            close = _to_float(row[close_index])
            extra = _to_float(row[index])
            if volume and close and extra and volume * close:
                ratios.append(extra / (volume * close))
        if len(ratios) < 3:
            continue
        ratios.sort()
        median = ratios[len(ratios) // 2]
        if 0.2 <= median <= 5 or 20 <= median <= 500:
            return index
    return None


# Two-decimal K-line payloads round these derived columns to 0.01 units.
_DERIVED_TOLERANCE = 0.021


def _infer_extra_semantics(
    matrix: Sequence[Sequence[str]],
    field_map: Mapping[str, int],
    candidates: Sequence[int],
) -> dict[int, str]:
    """Name headerless extra columns by verifying their OHLCV identities.

    Vendors disagree on the order of the columns after volume/amount, so no
    positional assumption is made. Amplitude, price change and percentage
    change each have an exact relation to consecutive rows; turnover rate has
    a near-constant ratio to volume. Only columns that satisfy one of these
    checks are named and marked ``inferred``. Everything else keeps its
    positional name and is still exposed to the view.
    """
    close_index = field_map.get("close")
    high_index = field_map.get("high")
    low_index = field_map.get("low")
    volume_index = field_map.get("volume")
    if close_index is None or high_index is None or low_index is None or len(matrix) < 4:
        return {}

    expected: dict[str, list[float]] = {
        "amplitude": [],
        "change": [],
        "change_pct": [],
    }
    volumes: list[float] = []
    for row_index in range(1, min(len(matrix), 50)):
        row, previous = matrix[row_index], matrix[row_index - 1]
        needed = (close_index, high_index, low_index)
        if any(len(row) <= index or len(previous) <= index for index in needed):
            break
        close = _to_float(row[close_index])
        previous_close = _to_float(previous[close_index])
        high = _to_float(row[high_index])
        low = _to_float(row[low_index])
        if (
            close is None
            or previous_close is None
            or high is None
            or low is None
            or previous_close == 0
        ):
            break
        expected["change"].append(close - previous_close)
        expected["change_pct"].append((close / previous_close - 1) * 100)
        expected["amplitude"].append((high - low) / previous_close * 100)
        volume = (
            _to_float(row[volume_index])
            if volume_index is not None and len(row) > volume_index
            else None
        )
        volumes.append(float(volume) if volume else float("nan"))
    count = len(expected["change"])
    if count < 3:
        return {}

    def column_values(index: int) -> list[float] | None:
        values = [
            _to_float(matrix[row_index][index])
            if len(matrix[row_index]) > index
            else None
            for row_index in range(1, count + 1)
        ]
        if any(value is None for value in values):
            return None
        return [float(value) for value in values]

    scored: list[tuple[float, int, str]] = []
    for index in candidates:
        values = column_values(index)
        if values is None:
            continue
        for semantic, series in expected.items():
            errors = sorted(abs(actual - target) for actual, target in zip(values, series))
            scored.append((errors[len(errors) // 2], index, semantic))

    assigned: dict[int, str] = {}
    used_semantics: set[str] = set()
    for error, index, semantic in sorted(scored):
        if error > _DERIVED_TOLERANCE or index in assigned or semantic in used_semantics:
            continue
        assigned[index] = semantic
        used_semantics.add(semantic)

    if "turnover_rate" not in used_semantics and volume_index is not None:
        for index in candidates:
            if index in assigned:
                continue
            values = column_values(index)
            if values is None or any(value <= 0 or value >= 100 for value in values):
                continue
            ratios = [
                value / volume
                for value, volume in zip(values, volumes)
                if math.isfinite(volume) and volume > 0
            ]
            if len(ratios) < 3:
                continue
            mean = sum(ratios) / len(ratios)
            if mean <= 0:
                continue
            deviation = math.sqrt(sum((ratio - mean) ** 2 for ratio in ratios) / len(ratios))
            if deviation / mean <= 0.25:
                assigned[index] = "turnover_rate"
                break
    return assigned


def infer_capability_fields(
    headers: Sequence[str], matrix: Sequence[Sequence[str]], explicit: bool
) -> tuple[dict[str, int], dict[str, dict[str, Any]], tuple[str, ...], list[str]]:
    """Return (standard field map, extra columns, inferred fields, missing fields)."""
    field_map: dict[str, int] = {}
    inferred: list[str] = []
    if explicit:
        for index, name in enumerate(headers):
            semantic = _match_alias(name)
            if semantic in STANDARD_FIELDS and semantic not in field_map:
                field_map[semantic] = index
    positional = _positional_map(matrix)
    if positional is not None:
        for semantic, index in positional.items():
            if semantic in field_map:
                continue
            field_map[semantic] = index
            if not explicit:
                inferred.append(semantic)
    missing = [field for field in REQUIRED_FIELDS if field not in field_map]
    if missing:
        raise DataDefinitionError(
            "The source response does not expose the required OHLC columns "
            f"({', '.join(missing)}); it cannot be used for a backtest."
        )

    used = set(field_map.values())
    extra: dict[str, dict[str, Any]] = {}
    amount_index = _infer_amount_index(matrix, field_map, 6)
    derived = _infer_extra_semantics(
        matrix, field_map, [index for index in range(len(headers)) if index not in used]
    )
    for index, name in enumerate(headers):
        if index in used:
            continue
        alias_semantic = _match_alias(name) if explicit else None
        semantic = alias_semantic or derived.get(index)
        if not explicit and index == amount_index:
            semantic = "amount"
        label = semantic or ("" if explicit else f"column_{index + 1}")
        if not label:
            label = name.strip() or f"column_{index + 1}"
        if label in field_map or label in extra:
            label = f"{label}_{index + 1}"
        numeric = all(
            _to_float(row[index]) is not None
            for row in matrix[:20]
            if len(row) > index and row[index] != ""
        ) and bool(matrix)
        extra[label] = {
            "index": index,
            "numeric": numeric,
            "inferred": bool(semantic)
            and (not explicit or index == amount_index or alias_semantic is None),
        }
    if "volume" not in field_map:
        field_map.pop("volume", None)
    return field_map, extra, tuple(inferred), [f for f in STANDARD_FIELDS if f not in field_map]


def _adapt_symbol(template: str, symbol: str) -> str:
    digits = re.search(r"\d{6}", symbol)
    if not digits:
        return symbol
    code = digits.group(0)
    if re.match(r"^\d\.\d{6}$", template):
        lowered = symbol.casefold()
        market = "1" if lowered.startswith("sh") or code.startswith(("5", "6", "9")) else "0"
        return f"{market}.{code}"
    prefix = re.match(r"^(sh|sz|bj)", template, re.I)
    if prefix:
        requested = re.match(r"^(sh|sz|bj)", symbol, re.I)
        market = requested.group(1) if requested else prefix.group(1)
        return f"{market.casefold()}{code}"
    if re.match(r"^\d{6}\.(SH|SZ)$", template, re.I):
        return f"{code}.{'SH' if symbol.casefold().startswith('sh') else 'SZ'}"
    return code


def _format_date(template: str, value: str) -> str:
    if _DATE_COMPACT_RE.match(template):
        return value.replace("-", "")[:8]
    return value[:10]


def _role_of_value(value: str) -> str | None:
    if _SYMBOL_RE.match(value):
        return "symbol"
    if _DATE_DASH_RE.match(value) or _DATE_COMPACT_RE.match(value):
        return "date"
    # A bare number is deliberately not a frequency here: inside a comma-string
    # spec it is the bar limit. Key-based parameters (klt=101) are recognised
    # by their key name in infer_parameter_bindings instead.
    if value.isdigit():
        return None
    if decode_frequency(value) is not None:
        return "frequency"
    if value.casefold() in _ADJUST_WORDS:
        return "adjust"
    return None


def infer_parameter_bindings(config: ApiSourceConfig) -> dict[str, Any]:
    """Infer how caller choices map onto this source's saved query parameters."""
    query = {str(key): str(value) for key, value in config.query.items()}

    for key, value in query.items():
        if "," not in value:
            continue
        parts = value.split(",")
        slots: list[str | None] = []
        for part in parts:
            role = _role_of_value(part.strip())
            if role == "date":
                role = "start" if "start" not in slots else "end"
            elif role is None and part.strip().isdigit():
                role = "limit"
            slots.append(role)
        # A structured spec must start with a symbol and carry at least one
        # other recognised slot. No fixed field count: different endpoints use
        # 4, 6 or more comma-separated fields (mkline vs fqkline/get).
        if "symbol" not in slots or not any(role is not None for role in slots[1:]):
            continue
        return {
            "kind": "csv",
            "key": key,
            "slots": slots,
            "templates": parts,
        }

    slots_by_key: dict[str, str] = {}
    dates: list[str] = []
    for key, value in query.items():
        lowered = key.casefold()
        role: str | None = None
        if _SYMBOL_RE.match(value) or lowered in ("symbol", "code", "secid", "ticker"):
            if _SYMBOL_RE.match(value) or re.search(r"\d{6}", value):
                role = "symbol"
        elif lowered in ("beg", "begin", "start", "startdate", "from", "start_date"):
            role = "start"
        elif lowered in ("end", "finish", "enddate", "to", "end_date"):
            role = "end"
        elif lowered in ("klt", "freq", "period", "frequency"):
            role = "frequency"
        elif lowered in ("fqt", "adjust", "adj"):
            role = "adjust"
        elif lowered in _LIMIT_KEYS:
            role = "limit"
        elif _DATE_DASH_RE.match(value) or _DATE_COMPACT_RE.match(value):
            role = "start" if not dates else "end"
        if role:
            slots_by_key[key] = role
            if role in ("start", "end"):
                dates.append(key)
    return {"kind": "keys", "slots": slots_by_key, "templates": dict(query)}


def _controllable(bindings: Mapping[str, Any], template: str, role: str) -> bool:
    if role == "frequency":
        return decode_frequency(template) is not None
    if role == "adjust":
        return template.strip().casefold() in _ADJUST_WORDS
    if role == "symbol":
        return bool(_SYMBOL_RE.match(template.strip()))
    if role in ("start", "end"):
        return bool(_DATE_DASH_RE.match(template.strip()) or _DATE_COMPACT_RE.match(template.strip()))
    return False


def build_request_spec(
    config: ApiSourceConfig,
    capability: Mapping[str, Any],
    *,
    symbol: str,
    start: str | None,
    end: str | None,
    frequency: str,
    adjust: str,
    limit: int | None = None,
) -> dict[str, str]:
    """Translate caller choices into query overrides, using the probed binding.

    Frequency travels as a canonical period id and is spelled back into the
    shape the source saved (klt=5, m5, day, 1h, ...); there is no per-source
    branch. Intraday requests on key-based endpoints use a recent bar window
    (end >= today + a limit) because those endpoints only serve recent bars;
    legacy values such as "day" are normalised to canonical ids first.
    """
    bindings = dict(capability.get("parameter_bindings") or {})
    spec: dict[str, str] = {}
    period = decode_frequency(frequency) or frequency
    intraday = is_intraday(period)
    today = date.today().isoformat()
    if limit is None and start and end:
        # Callers that do not pass a limit keep the historical window-derived
        # default; fetch_bar_records passes a frequency-aware limit instead.
        try:
            days = (
                date.fromisoformat((end or "")[:10]) - date.fromisoformat((start or "")[:10])
            ).days
            limit_value = str(max(60, min(1000, int(max(days, 0) * 0.8) + 60)))
        except (TypeError, ValueError):
            limit_value = ""
    else:
        limit_value = str(limit) if limit and limit > 0 else ""
    values = {
        "symbol": symbol.strip(),
        "start": (start or "").strip(),
        "end": (end or "").strip(),
        "frequency": period,
        "adjust": adjust,
        "limit": limit_value,
    }

    def encode(role: str, template: str, value: str) -> str | None:
        if role == "symbol":
            return _adapt_symbol(template.strip(), value)
        if role in ("start", "end"):
            if role == "start" and intraday:
                return None  # recent-window endpoints ignore a historical start
            stamp = max(value[:10], today) if intraday else value
            return _format_date(template.strip(), stamp)
        if role == "frequency":
            return encode_frequency(template, value) or value
        return value

    if bindings.get("kind") == "csv":
        key = str(bindings.get("key") or "param")
        slots = list(bindings.get("slots") or [])
        templates = [str(item) for item in bindings.get("templates") or []]
        parts = list(templates)
        for index, role in enumerate(slots):
            if index >= len(parts):
                continue
            template = parts[index]
            if role == "limit":
                if limit_value:
                    parts[index] = limit_value
                continue
            if role not in values or not _controllable(bindings, template, role):
                continue
            value = values[role]
            if not value and role != "adjust":
                continue
            encoded = encode(role, template, value)
            if encoded is not None:
                parts[index] = encoded
        spec[key] = ",".join(parts)
        return spec

    slots = dict(bindings.get("slots") or {})
    templates = dict(bindings.get("templates") or {})
    for key, role in slots.items():
        template = str(templates.get(key, ""))
        if role == "limit":
            if limit_value:
                spec[key] = limit_value
            continue
        if role not in values or not _controllable(bindings, template, role):
            continue
        value = values[role]
        if not value and role != "adjust":
            continue
        encoded = encode(role, template, value)
        if encoded is not None:
            spec[key] = encoded
    if intraday and "limit" not in slots.values():
        spec.setdefault(_DEFAULT_LIMIT_KEY, limit_value or "320")
    return spec


def decode_bar_records(raw: bytes, capability: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Decode a live response into bar records named by the probed capability."""
    headers, matrix, layout = _decode_table(raw)
    field_map = {str(k): int(v) for k, v in (capability.get("field_map") or {}).items()}
    extra = {
        str(name): dict(spec)
        for name, spec in (capability.get("extra_columns") or {}).items()
    }
    if not field_map:
        raise DataDefinitionError("The source capability has no field map.")

    records: list[dict[str, Any]] = []
    numeric_fields = set(STANDARD_FIELDS) - {"date"}
    for row in matrix:
        record: dict[str, Any] = {}
        for semantic, index in field_map.items():
            if index >= len(row):
                raise DataDefinitionError(
                    "The source response has fewer columns than its recorded capability."
                )
            value: Any = row[index]
            if semantic in numeric_fields:
                parsed = _to_float(value)
                if parsed is None:
                    raise DataDefinitionError(
                        f"Column '{semantic}' has a non-numeric value: {value!r}."
                    )
                value = parsed
            record[semantic] = value
        for name, spec in extra.items():
            index = int(spec.get("index", -1))
            if index < 0 or index >= len(row):
                continue
            value = row[index]
            record[name] = _to_float(value) if spec.get("numeric") and value != "" else value
        record.setdefault("volume", 0.0)
        records.append(record)
    if not records:
        raise DataDefinitionError("The source returned no bar rows.")
    return records


def _adapter_for(config: ApiSourceConfig) -> Any:
    if config.kind == "local":
        return ConfiguredLocalAdapter(config)
    return ConfiguredHttpAdapter(config)


def fetch_source_bytes(config: ApiSourceConfig, spec: Mapping[str, str] | None = None) -> bytes:
    """Fetch raw bytes through Data's own configured adapter (never a new client)."""
    request = FetchRequest(
        source_type=config.key,
        spec=dict(spec or {}),
        mode=AcquisitionMode.BATCH,
        cursor=None,
    )
    result = _adapter_for(config).fetch(request)
    return b"".join(result.chunks)


def build_capability(config: ApiSourceConfig, raw: bytes) -> dict[str, Any]:
    """Build a capability declaration from one sample response (pure)."""
    signature = source_signature(config)
    bindings = infer_parameter_bindings(config)
    base: dict[str, Any] = {
        "signature": signature,
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "status": "ready",
        "error": None,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "parameter_bindings": bindings,
        "frequency_options": frequency_options(frequency_template(bindings)),
    }
    try:
        headers, matrix, layout = _decode_table(raw)
        field_map, extra, inferred, missing = infer_capability_fields(
            headers, matrix, bool(layout.get("explicit"))
        )
    except Exception as exc:  # probing is best-effort; never blocks registration
        base.update(
            {
                "status": "unavailable",
                "error": str(exc),
                "columns": [],
                "missing_columns": list(STANDARD_FIELDS),
                "field_map": {},
                "extra_columns": {},
                "layout": {},
                "sample_rows": 0,
                "inferred_columns": [],
                "controllable": [],
            }
        )
        return base

    bindings = base["parameter_bindings"]
    templates = (
        bindings.get("templates", {})
        if bindings.get("kind") == "csv"
        else bindings.get("templates", {})
    )
    controllable: list[str] = []
    if bindings.get("kind") == "csv":
        pairs = [
            (str(item), role)
            for item, role in zip(templates, bindings.get("slots") or [])
            if role in ("symbol", "start", "end", "frequency", "adjust")
        ]
    else:
        pairs = [
            (str(templates.get(key, "")), role)
            for key, role in (bindings.get("slots") or {}).items()
            if role in ("symbol", "start", "end", "frequency", "adjust")
        ]
    for template, role in pairs:
        if _controllable(bindings, template, role) and role not in controllable:
            controllable.append(role)

    columns = [field for field in STANDARD_FIELDS if field in field_map] + list(extra)
    base.update(
        {
            "layout": layout,
            "raw_columns": list(headers),
            "columns": columns,
            "missing_columns": missing,
            "field_map": field_map,
            "extra_columns": extra,
            "inferred_columns": [
                *inferred,
                *[name for name, spec in extra.items() if spec.get("inferred")],
            ],
            "sample_rows": len(matrix),
            "controllable": controllable,
        }
    )
    return base


def probe_source(config: ApiSourceConfig) -> dict[str, Any]:
    """Probe one saved source by fetching a sample response through Data."""
    try:
        probe_config = (
            replace(config, timeout=min(float(config.timeout), 4.0))
            if config.kind == "api"
            else config
        )
        return build_capability(config, fetch_source_bytes(probe_config))
    except Exception as exc:  # probing is best-effort; never blocks registration
        capability = build_capability(config, b"")
        capability["error"] = str(exc)
        return capability


def get_or_probe(
    store: SourceCapabilityStore,
    config: ApiSourceConfig,
) -> dict[str, Any]:
    """Return a cached capability, re-probing when the source or rules changed."""
    signature = source_signature(config)
    cached = store.get(config.key)
    if (
        cached is not None
        and cached.get("signature") == signature
        and cached.get("schema_version") == CAPABILITY_SCHEMA_VERSION
    ):
        return cached
    return store.save(config.key, probe_source(config))
