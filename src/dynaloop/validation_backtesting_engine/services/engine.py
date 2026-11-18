"""Deterministic event loop (qlib ``backtest_loop`` causality, ml4t lifecycle).

For each frame the engine:
  1. settles orders that became eligible at this bar,
  2. hands the strategy a point-in-time view truncated at this bar,
  3. queues new orders for a later bar (NEXT_BAR) or settles them immediately
     on the same bar (SAME_BAR, which emits a look-ahead warning),
  4. marks the account to market using a separate price source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from itertools import count
from typing import Any, Iterable

from dynaloop.validation_backtesting_engine.domain.models import (
    BacktestConfig,
    BacktestError,
    ExecutionMode,
    Fill,
    Order,
    OrderStatus,
)
from dynaloop.validation_backtesting_engine.feed import BarView, StaticFeed
from dynaloop.validation_backtesting_engine.interfaces.protocols import DataFeed, Strategy
from dynaloop.validation_backtesting_engine.services.account import Account
from dynaloop.validation_backtesting_engine.services.exchange import Exchange
from dynaloop.validation_backtesting_engine.services.report import BacktestResult, build_result


@dataclass(slots=True)
class StrategyContext:
    """State the engine exposes to a strategy; no future feed data."""

    config: BacktestConfig
    warnings: list[str] = field(default_factory=list)
    bar_index: int = 0


class Broker:
    """Order submission surface passed to ``Strategy.on_data``."""

    def __init__(self, engine: "Engine", account: Account, bar_index: int) -> None:
        self._engine = engine
        self._account = account
        self._bar_index = bar_index
        self.submitted: list[Order] = []

    def submit_order(self, symbol: str, quantity: float) -> Order:
        if not isinstance(symbol, str) or not symbol.strip():
            raise BacktestError("Order symbol must be a non-empty string.")
        value = float(quantity)
        if not math.isfinite(value) or value == 0:
            raise BacktestError("Order quantity must be a finite non-zero number.")
        same_bar = self._engine.config.execution_mode is ExecutionMode.SAME_BAR
        order = Order(
            order_id=self._engine.next_order_id(),
            symbol=symbol.strip(),
            quantity=value,
            submitted_index=self._bar_index,
            eligible_index=self._bar_index if same_bar else self._bar_index + 1,
        )
        self.submitted.append(order)
        return order

    @property
    def cash(self) -> float:
        return self._account.cash

    @property
    def positions(self) -> dict[str, float]:
        return self._account.positions


class Engine:
    """Runs one backtest over a feed view; all state is per-run."""

    def __init__(
        self,
        feed: DataFeed | StaticFeed,
        strategy: Strategy,
        config: BacktestConfig | None = None,
    ) -> None:
        self.feed = feed
        self.strategy = strategy
        self.config = config or BacktestConfig()
        self.orders: list[Order] = []
        self._order_counter = count(1)

    def next_order_id(self) -> str:
        return f"o-{next(self._order_counter)}"

    def run(self, *, start: str | None = None, end: str | None = None) -> BacktestResult:
        warnings = list(self.config.validate())
        window = self.feed.window(start, end)
        frames = window.frames
        if not frames:
            raise BacktestError(
                "No bars in the selected window; adjust start/end or the data feed."
            )

        # Fresh state for every run: two windows over one frozen feed cannot
        # leak positions, cash, ids or warnings into each other.
        self.orders = []
        self._order_counter = count(1)
        account = Account(self.config)
        exchange = Exchange(self.config)
        context = StrategyContext(self.config, warnings)
        fills: list[Fill] = []
        states: list[dict[str, Any]] = []
        pending: list[Order] = []

        self.strategy.on_start(self.config)
        self.strategy.on_prepare(self.config)  # config only; no feed timestamps

        for index, frame in enumerate(frames):
            context.bar_index = index

            eligible = [order for order in pending if order.eligible_index <= index]
            if eligible:
                self._settle(exchange.match(eligible, frame, index, account), account, fills)
                eligible_ids = {order.order_id for order in eligible}
                pending = [order for order in pending if order.order_id not in eligible_ids]

            broker = Broker(self, account, index)
            # Truncated view: bar t can never see bar t+1.
            self.strategy.on_data(frame.timestamp, BarView(frames[: index + 1]), context, broker)
            self.orders.extend(broker.submitted)

            if broker.submitted:
                if self.config.execution_mode is ExecutionMode.SAME_BAR:
                    self._settle(
                        exchange.match(broker.submitted, frame, index, account),
                        account,
                        fills,
                    )
                else:
                    pending.extend(broker.submitted)

            account.mark_to_market(frame, self.config.mark_price)
            states.append(account.snapshot(index, frame.timestamp))

        for order in pending:
            self._replace_order(
                replace(order, status=OrderStatus.CANCELLED, reason="window ended before eligibility")
            )

        result = build_result(
            config=self.config,
            frames=frames,
            feed_metadata=window.metadata,
            orders=self.orders,
            fills=fills,
            states=states,
            warnings=tuple(warnings),
        )
        self.strategy.on_end(result)
        return result

    def _settle(
        self,
        outcome: tuple[Iterable[Fill], Iterable[Order]],
        account: Account,
        ledger: list[Fill],
    ) -> None:
        new_fills, updated_orders = outcome
        for fill in new_fills:
            ledger.append(fill)
        for order in updated_orders:
            self._replace_order(order)

    def _replace_order(self, order: Order) -> None:
        self.orders = [
            order if existing.order_id == order.order_id else existing
            for existing in self.orders
        ]
