"""Backtest result, descriptive metrics and reproducibility artifacts.

Following ml4t/backtest, the resolved config and the runtime spec are separate:
``config.yaml``-equivalent holds fully expanded defaults, while
``spec.yaml``-equivalent records library versions and the *realized* window
and bar count. No wall-clock timestamp enters the result, so the same run is
bit-identical on replay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from dynaloop.infrastructure import fingerprint, library_versions

from dynaloop.validation_backtesting_engine.domain.models import (
    BacktestConfig,
    Fill,
    Frame,
    Order,
)


def _reconciliation_error(state: Mapping[str, Any]) -> float:
    marked = sum(
        quantity * state["marks"].get(symbol, 0.0)
        for symbol, quantity in state["positions"].items()
    )
    return float(state["cash"]) + marked - float(state["equity"])


def _buy_and_hold(
    config: BacktestConfig, frames: Sequence[Frame]
) -> dict[str, Any] | None:
    """Descriptive, axis-aligned baseline over exactly the same bars."""
    if config.benchmark != "buy_and_hold" or not frames:
        return None
    first = frames[0]
    symbols = first.symbols()
    if not symbols:
        return None
    symbol = str(config.metadata.get("benchmark_symbol") or symbols[0])
    bar = first.get(symbol)
    if bar is None:
        return None
    from dynaloop.validation_backtesting_engine.services.account import Account
    from dynaloop.validation_backtesting_engine.services.exchange import Exchange

    price = bar.price(config.execution_price)
    if price <= 0:
        return None
    benchmark_config = replace(config, reject_on_insufficient_cash=False)
    account = Account(benchmark_config)
    fills, _ = Exchange(benchmark_config).match(
        [Order("benchmark", symbol, config.initial_cash / price, 0, 0)],
        first, 0, account,
    )
    quantity = account.position.quantity(symbol)
    equity: list[float] = []
    for frame in frames:
        account.mark_to_market(frame, config.mark_price)
        equity.append(account.equity)
    return {
        "type": "buy_and_hold",
        "symbol": symbol,
        "quantity": quantity,
        "equity": equity,
        "total_return": equity[-1] / config.initial_cash - 1,
        "aligned_bar_count": len(frames),
        "entry_timing": "first observed bar (descriptive benchmark)",
        "fills": [fill.to_dict() for fill in fills],
    }


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Deterministic, self-describing result of one backtest run."""

    resolved_config: dict[str, Any]
    spec: dict[str, Any]
    warnings: tuple[str, ...]
    orders: tuple[dict[str, Any], ...]
    fills: tuple[dict[str, Any], ...]
    portfolio_state: tuple[dict[str, Any], ...]
    metrics: dict[str, Any] = field(default_factory=dict)
    benchmark: dict[str, Any] | None = None
    # Per-bar OHLCV frames: the immutable tape a UI can replay without ever
    # re-running the engine (ml4t's equity/portfolio snapshots made explicit).
    bars: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolved_config": self.resolved_config,
            "spec": self.spec,
            "warnings": list(self.warnings),
            "orders": list(self.orders),
            "fills": list(self.fills),
            "portfolio_state": list(self.portfolio_state),
            "metrics": self.metrics,
            "benchmark": self.benchmark,
            "bars": list(self.bars),
        }

    def fingerprint(self) -> str:
        """Identity of the deterministic part of the run (no wall clock)."""
        payload = {
            "resolved_config": self.resolved_config,
            "fills": list(self.fills),
            "portfolio_state": list(self.portfolio_state),
            "orders": list(self.orders),
            "spec": self.spec,
            "bars": list(self.bars),
            "metrics": self.metrics,
            "benchmark": self.benchmark,
            "warnings": list(self.warnings),
        }
        return fingerprint(payload)


def build_result(
    *,
    config: BacktestConfig,
    frames: Sequence[Frame],
    feed_metadata: Mapping[str, Any],
    orders: Sequence[Order],
    fills: Sequence[Fill],
    states: Sequence[Mapping[str, Any]],
    warnings: tuple[str, ...],
) -> BacktestResult:
    resolved = config.to_dict()
    equity = [float(state["equity"]) for state in states]
    initial = float(config.initial_cash)
    final = equity[-1] if equity else initial

    peak = initial
    max_drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, value / peak - 1)

    settled = [fill for fill in fills if fill.status != "rejected"]
    traded_value = sum(abs(fill.quantity * fill.price) for fill in settled)
    reconciliation = max((abs(_reconciliation_error(state)) for state in states), default=0.0)

    metrics: dict[str, Any] = {
        "initial_cash": initial,
        "final_equity": final,
        "total_return": final / initial - 1,
        "max_drawdown": max_drawdown,
        "turnover": traded_value / initial,
        "bar_count": len(states),
        "fill_count": len(settled),
        "rejected_count": len(fills) - len(settled),
        "final_positions": dict(states[-1]["positions"]) if states else {},
        "reconciliation_max_abs": reconciliation,
        "annualized_volatility": None,
        "sharpe_ratio": None,
    }

    if config.periods_per_year and len(equity) > 2:
        changes = [
            equity[index] / equity[index - 1] - 1
            for index in range(1, len(equity))
            if equity[index - 1] > 0
        ]
        if changes:
            mean = sum(changes) / len(changes)
            variance = sum((value - mean) ** 2 for value in changes) / len(changes)
            deviation = math.sqrt(variance)
            annualized = deviation * math.sqrt(config.periods_per_year)
            metrics["annualized_volatility"] = annualized
            metrics["sharpe_ratio"] = (
                mean / deviation * math.sqrt(config.periods_per_year) if deviation else None
            )

    symbols: set[str] = set()
    for frame in frames:
        symbols.update(frame.symbols())

    spec = {
        "schema_version": 2,
        "realized_window": {
            "start": frames[0].timestamp if frames else None,
            "end": frames[-1].timestamp if frames else None,
        },
        "bar_count": len(frames),
        "symbols": sorted(symbols),
        "library_versions": library_versions(),
        "config_fingerprint": fingerprint(resolved),
        "feed_metadata": dict(feed_metadata),
    }
    return BacktestResult(
        resolved_config=resolved,
        spec=spec,
        warnings=warnings,
        orders=tuple(order.to_dict() for order in orders),
        fills=tuple(fill.to_dict() for fill in fills),
        portfolio_state=tuple(dict(state) for state in states),
        metrics=metrics,
        benchmark=_buy_and_hold(config, frames),
        bars=tuple(frame.to_dict() for frame in frames),
    )
