"""Market-data view over the Data module's own registered sources.

Source recipes, symbol catalogues and payload decoding belong to Data. Other
modules (for example Validation & Backtesting) contact Data through the two
public helpers below and never reach into adapters or registries themselves.
No dataset or version is published for an on-demand read.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from dynaloop.data.domain.errors import DataDefinitionError
from dynaloop.data.services.adapter_registry import AdapterRegistry
from dynaloop.data.services.api_source import (
    ApiSourceConfig,
    ApiSourceStore,
    ConfiguredHttpAdapter,
)
from dynaloop.data.services.source_capabilities import (
    MINUTES_PER_SESSION,
    PERIOD_OPTIONS,
    STANDARD_FIELDS,
    SourceCapabilityStore,
    build_request_spec,
    decode_bar_records,
    decode_frequency,
    fetch_source_bytes,
    frequency_options,
    get_or_probe,
    is_intraday,
    period_minutes,
    time_key,
)

# Selectable A-share instruments for the demo. These are caller choices, not
# engine constants; ``__custom__`` in the UI accepts any code the source takes.
ASHARE_SYMBOLS: tuple[dict[str, str], ...] = (
    {"symbol": "sh600000", "name": "SPD Bank", "kind": "Stock"},
    {"symbol": "sh600519", "name": "Kweichow Moutai", "kind": "Stock"},
    {"symbol": "sz000001", "name": "Ping An Bank", "kind": "Stock"},
    {"symbol": "sh601318", "name": "Ping An Insurance", "kind": "Stock"},
    {"symbol": "sh510300", "name": "CSI 300 ETF", "kind": "ETF"},
    {"symbol": "sh510500", "name": "CSI 500 ETF", "kind": "ETF"},
    {"symbol": "sh588000", "name": "STAR 50 ETF", "kind": "ETF"},
    {"symbol": "sz159915", "name": "ChiNext ETF", "kind": "ETF"},
)

# Canonical periods are declared by each probed source. This list is only a
# static fallback for sources whose capability has not been probed yet; it is
# never an allow-list for what a source may serve.
FREQUENCIES: tuple[dict[str, str], ...] = tuple(
    {"value": item["value"], "label": item["label"]} for item in PERIOD_OPTIONS
)

ADJUSTMENTS: tuple[dict[str, str], ...] = (
    {"value": "qfq", "label": "Forward-adjusted (qfq)"},
    {"value": "hfq", "label": "Backward-adjusted (hfq)"},
    {"value": "", "label": "Unadjusted"},
)

# A source that can answer "give me OHLCV for symbol X over window [a, b]".
# The recipe describes how to encode those choices into the source's own spec.
SOURCE_PRESETS: dict[str, dict[str, Any]] = {
    "tencent_ashare": {
        "label": "A-share · Tencent K-line",
        "format_id": "kline-json",
        "columns": ("date", "open", "high", "low", "close", "volume"),
        "frequencies": frequency_options("day"),
        "adjustments": ADJUSTMENTS,
        "symbols": ASHARE_SYMBOLS,
        "default_start": "2024-01-02",
        "default_end": "2024-06-28",
        "description": "Daily, weekly and monthly OHLCV bars for A-share stocks and ETFs via Tencent fqkline/get.",
    },
    "tencent_ashare_minute": {
        "label": "A-share · Tencent intraday K-line",
        "format_id": "kline-json",
        "columns": ("date", "open", "high", "low", "close", "volume"),
        "frequencies": frequency_options("m5"),
        "adjustments": (),
        "symbols": ASHARE_SYMBOLS,
        "default_start": "2026-11-01",
        "default_end": "2026-11-10",
        "description": "1, 5, 15, 30 and 60 minute OHLCV bars via Tencent mkline (recent bars only).",
    },
}

# Built-in recipes belong to Data. They are used on demand by
# ``fetch_bar_records`` and are never written to the user's ApiSourceStore or
# injected into the shared adapter registry, so the Data page and the adapter
# catalogue keep exactly the sources the user configured. A recipe explicitly
# saved under the same key always wins.
BUILTIN_MARKET_SOURCES: dict[str, ApiSourceConfig] = {
    "tencent_ashare": ApiSourceConfig(
        key="tencent_ashare",
        name="A-share (Tencent)",
        url="https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        method="GET",
        query={"param": "sh600000,day,2024-01-01,2024-01-31,20,qfq"},
    ),
    # Intraday bars live on a different Tencent endpoint with a different row
    # key (m5, m60, ...). Registering it as its own source keeps the generic
    # decoder unchanged: the capability probe finds the timestamp-led table.
    "tencent_ashare_minute": ApiSourceConfig(
        key="tencent_ashare_minute",
        name="A-share intraday (Tencent)",
        url="https://ifzq.gtimg.cn/appstock/app/kline/mkline",
        method="GET",
        query={"param": "sh600000,m5,,320"},
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    ),
}


def resolve_market_source(
    registries: tuple[AdapterRegistry[Any], AdapterRegistry[Any]],
    source_key: str,
) -> Any:
    """Resolve a bar-capable source adapter, preferring the user's own config.

    Reuses Data's ``ConfiguredHttpAdapter`` for the built-in recipe instead of
    implementing another HTTP client. This keeps the shared registry unchanged.
    """
    source_registry, _ = registries
    if source_key in source_registry.keys():
        return source_registry.create(source_key)
    builtin = BUILTIN_MARKET_SOURCES.get(source_key)
    if builtin is not None:
        return ConfiguredHttpAdapter(builtin)
    raise DataDefinitionError(f"Data source '{source_key}' is not registered.")


def _capability_store(explicit: SourceCapabilityStore | None) -> SourceCapabilityStore:
    """Use the injected store, or fall back to the user's Data state directory."""
    if explicit is not None:
        return explicit
    return SourceCapabilityStore(Path.home() / ".dynaloop" / "source_capabilities.json")


def list_backtest_sources(
    store: ApiSourceStore,
    registries: tuple[AdapterRegistry[Any], AdapterRegistry[Any]],
    capability_store: SourceCapabilityStore | None = None,
) -> list[dict[str, Any]]:
    """Catalogue every registered source with its probed capabilities.

    A source saved in Data is usable with no adapter code: its capability is
    probed on demand and cached. Built-in recipes carry a static declaration so
    a clean install never needs a network round trip just to list sources.
    """
    registered = {config.key: config for config in store.list_all()}
    builtin = BUILTIN_MARKET_SOURCES
    capabilities = _capability_store(capability_store)
    rows: list[dict[str, Any]] = []
    for key in sorted(set(registered) | set(builtin) | set(SOURCE_PRESETS)):
        config = registered.get(key) or builtin.get(key)
        preset = SOURCE_PRESETS.get(key)
        capability: dict[str, Any] = {}
        if key in registered and config is not None:
            capability = dict(get_or_probe(capabilities, config))
        probed = capability.get("status") == "ready"
        declared = key not in registered and preset is not None
        columns = list(
            capability.get("columns") or (preset or {}).get("columns") or []
        )
        controllable = list(
            capability.get("controllable")
            or (["symbol", "start", "end", "frequency", "adjust"] if declared else [])
        )
        rows.append(
            {
                "key": key,
                "name": config.name if config is not None else (preset or {}).get("label", key),
                "kind": config.kind if config is not None else "api",
                "endpoint": (
                    config.url.split("?", 1)[0]
                    if config is not None and config.kind == "api"
                    else None
                ),
                "registered": config is not None,
                "builtin": key in builtin and key not in registered,
                "compatible": bool((probed or declared) and config is not None),
                "capability_status": capability.get(
                    "status", "declared" if declared else "unavailable"
                ),
                "capability_error": capability.get("error"),
                "columns": columns,
                "missing_columns": [f for f in STANDARD_FIELDS if f not in columns],
                "extra_columns": list((capability.get("extra_columns") or {}).keys()),
                "inferred_columns": list(capability.get("inferred_columns") or []),
                "controllable": controllable,
                "format_id": "auto" if probed else (preset or {}).get("format_id"),
                "frequencies": list(
                    capability.get("frequency_options")
                    or (preset or {}).get("frequencies")
                    or (FREQUENCIES if "frequency" in controllable else [])
                ),
                "adjustments": list(
                    (preset or {}).get("adjustments")
                    or (ADJUSTMENTS if "adjust" in controllable else [])
                ),
                "symbols": list(
                    (preset or {}).get("symbols")
                    or (ASHARE_SYMBOLS if "symbol" in controllable else [])
                ),
                "default_start": (preset or {}).get("default_start", ""),
                "default_end": (preset or {}).get("default_end", ""),
                "description": (preset or {}).get("description", "")
                or "Capabilities detected automatically from the source response.",
            }
        )
    return rows


def _bar_limit(start: str | None, end: str | None, frequency: str) -> int:
    """Rows to request; intraday periods need several bars per session."""
    period = decode_frequency(frequency) or frequency
    try:
        days = (
            date.fromisoformat((end or "")[:10]) - date.fromisoformat((start or "")[:10])
        ).days
    except (TypeError, ValueError):
        return 1000
    if is_intraday(period):
        bars_per_day = max(1, MINUTES_PER_SESSION // max(1, period_minutes(period)))
        return max(60, min(1000, int(max(days, 1) * bars_per_day) + 60))
    return max(60, min(1000, int(max(days, 0) * 0.8) + 60))


def fetch_bar_records(
    registries: tuple[AdapterRegistry[Any], AdapterRegistry[Any]],
    *,
    source_key: str,
    symbol: str,
    start: str | None,
    end: str | None,
    frequency: str = "1d",
    adjust: str = "qfq",
    capability_store: SourceCapabilityStore | None = None,
    store: ApiSourceStore | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch one symbol's bars through Data using only its probed declaration.

    No per-source branching: parameter bindings, decoding and column semantics
    all come from the capability cached when the source was registered.
    """
    config: ApiSourceConfig | None = store.get(source_key) if store is not None else None
    if config is None:
        try:
            adapter = resolve_market_source(registries, source_key)
            config = getattr(adapter, "config", None)
        except DataDefinitionError:
            config = None
    if config is None:
        raise DataDefinitionError(
            f"Source '{source_key}' is not registered and has no usable configuration."
        )
    if not isinstance(symbol, str) or not symbol.strip():
        raise DataDefinitionError("A symbol is required.")

    capabilities = _capability_store(capability_store)
    capability = get_or_probe(capabilities, config)
    if capability.get("status") != "ready":
        raise DataDefinitionError(
            f"Source '{source_key}' cannot supply bar records: "
            f"{capability.get('error') or 'no table detected'}."
        )

    period = decode_frequency(frequency) or frequency
    intraday = is_intraday(period)
    spec = build_request_spec(
        config,
        capability,
        symbol=symbol.strip(),
        start=start,
        end=end,
        frequency=frequency,
        adjust=adjust,
        limit=_bar_limit(start, end, frequency),
    )
    rows = decode_bar_records(fetch_source_bytes(config, spec), capability)
    # Intraday endpoints serve a recent window rather than an arbitrary date
    # range. Cropping those rows by the caller's window would drop every bar,
    # so the realised window is recorded instead and used as the run window.
    if not intraday:
        lower = time_key(start) if start else None
        upper = time_key(end) if end else None
        if lower or upper:
            rows = [
                row
                for row in rows
                if (lower is None or time_key(row.get("date")) >= lower)
                and (upper is None or time_key(row.get("date")) <= upper)
            ]
    if not rows:
        raise DataDefinitionError(
            "The source returned no bars for this symbol and time window."
        )
    resolved_window = {
        "start": str(rows[0].get("date") or ""),
        "end": str(rows[-1].get("date") or ""),
    }
    metadata: dict[str, Any] = {
        "source_key": source_key,
        "request_param": spec.get("param") or json.dumps(spec, sort_keys=True),
        "request_spec": spec,
        "symbol": symbol.strip(),
        "format_id": "auto",
        "fetch_window": {"start": start, "end": end},
        "resolved_window": resolved_window,
        "recent_window": intraday,
        "frequency": frequency,
        "frequency_period": period,
        "adjust": adjust,
        "fetched_rows": len(rows),
        "columns": list(capability.get("columns") or []),
        "missing_columns": list(capability.get("missing_columns") or []),
        "controllable": list(capability.get("controllable") or []),
    }
    return rows, metadata
