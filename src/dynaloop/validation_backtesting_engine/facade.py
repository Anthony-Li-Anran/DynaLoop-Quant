"""Public entry points for running a backtest.

The engine imports no other DynaLoop module's domain types. ``records_provider``
in ``run_saved_config`` is supplied by the caller (the API adapter), which is
where Data-module types are translated into plain JSON-lines records.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from dynaloop.validation_backtesting_engine.domain.models import (
    BacktestConfig,
    BacktestError,
)
from dynaloop.validation_backtesting_engine.feed import StaticFeed
from dynaloop.validation_backtesting_engine.interfaces.protocols import DataFeed, Strategy
from dynaloop.validation_backtesting_engine.services.engine import Engine
from dynaloop.validation_backtesting_engine.services.report import BacktestResult
from dynaloop.validation_backtesting_engine.strategies import build_strategy

RecordsProvider = Callable[[str, str], Iterable[Mapping[str, Any]]]


def run_backtest(
    feed: DataFeed | StaticFeed,
    strategy: Strategy,
    config: BacktestConfig | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
) -> BacktestResult:
    """Run over an optional caller-supplied window (omitted = full feed)."""
    return Engine(feed, strategy, config).run(start=start, end=end)


def backtest_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    strategy: Strategy,
    config: BacktestConfig | None = None,
    start: str | None = None,
    end: str | None = None,
    **feed_options: Any,
) -> BacktestResult:
    """Convenience adapter: JSON-lines records -> feed -> engine."""
    feed = StaticFeed.from_records(records, symbol=symbol, **feed_options)
    return run_backtest(feed, strategy, config, start=start, end=end)


def _values(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        return dict(record.to_dict())
    if isinstance(record, Mapping):
        return dict(record)
    raise BacktestError("run config must be a RunConfigRecord or a mapping.")


def run_saved_config(
    record: Any,
    records_provider: RecordsProvider,
    *,
    start: str | None = None,
    end: str | None = None,
) -> BacktestResult:
    """Replay a saved run configuration end-to-end.

    Symbol, window, capital, strategy class + kwargs and execution knobs all
    come from the caller; the engine contains none of them as constants.
    """
    values = _values(record)
    for key in ("dataset_id", "version_id", "symbol", "strategy_class"):
        if not values.get(key):
            raise BacktestError(f"run config is missing {key!r}.")

    execution = dict(values.get("execution") or {})
    execution["initial_cash"] = float(values.get("initial_cash", 100_000.0))
    metadata = {
        "config_id": values.get("config_id"),
        "dataset_id": values["dataset_id"],
        "version_id": values["version_id"],
        "symbol": values["symbol"],
        **dict(values.get("metadata") or {}),
        **dict(execution.get("metadata") or {}),
    }
    execution["metadata"] = metadata
    config = BacktestConfig.from_dict(execution)
    strategy = build_strategy(
        str(values["strategy_class"]), values.get("strategy_kwargs") or {}
    )
    records = records_provider(values["dataset_id"], values["version_id"])
    feed = StaticFeed.from_records(
        records,
        symbol=values["symbol"],
        metadata={
            "dataset_id": values["dataset_id"],
            "version_id": values["version_id"],
            "symbol": values["symbol"],
        },
    )
    return Engine(feed, strategy, config).run(
        start=start if start is not None else values.get("start"),
        end=end if end is not None else values.get("end"),
    )
