"""Exchange: pricing, fees, order ordering and cash/position checks.

Execution timing (``ExecutionMode``) and execution price source
(``PriceSource``) are orthogonal knobs, matching ml4t/backtest. Keeping them
separate is what prevents the silent semantic drift documented in that
project's cross-engine stress test.
"""

from __future__ import annotations

import math
from dataclasses import replace
from itertools import count
from typing import Sequence

from dynaloop.validation_backtesting_engine.domain.models import (
    BacktestConfig,
    Fill,
    FillOrdering,
    Frame,
    Order,
    OrderStatus,
    ShareType,
)
from dynaloop.validation_backtesting_engine.services.account import Account


class Exchange:
    def __init__(self, config: BacktestConfig) -> None:
        self._config = config
        self._fill_ids = count(1)

    def _ordered(self, orders: Sequence[Order]) -> list[Order]:
        ordering = self._config.fill_ordering
        if ordering is FillOrdering.FIFO:
            return sorted(orders, key=lambda order: order.submitted_index)
        if ordering is FillOrdering.EXIT_FIRST:
            return sorted(
                orders,
                key=lambda order: (
                    0 if order.quantity < 0 else 1,
                    order.submitted_index,
                ),
            )
        return list(orders)

    def _align(self, quantity: float) -> float:
        magnitude = abs(quantity)
        if self._config.share_type is ShareType.INTEGER:
            lot = self._config.lot_size
            magnitude = math.floor(magnitude / lot + 1e-12) * lot
        return math.copysign(magnitude, quantity)

    def match(
        self,
        orders: Sequence[Order],
        frame: Frame,
        bar_index: int,
        account: Account,
    ) -> tuple[list[Fill], list[Order]]:
        """Settle orders sequentially and return their fills and updated orders.

        Partial fills are terminal for the remainder (cancelled), which keeps
        the deterministic ledger free of repeated queue state.
        """
        fills: list[Fill] = []
        updated: list[Order] = []
        for order in self._ordered(orders):
            fill = self._attempt(order, frame, bar_index, account, updated)
            account.apply_fill(fill)
            fills.append(fill)
        return fills, updated

    def _attempt(
        self,
        order: Order,
        frame: Frame,
        bar_index: int,
        account: Account,
        updated: list[Order],
    ) -> Fill:
        fill_id = f"f-{next(self._fill_ids)}"

        def record(
            quantity: float,
            price: float,
            commission: float,
            slippage: float,
            cash_delta: float,
            status: str,
            reason: str,
        ) -> Fill:
            order_status = {
                "filled": OrderStatus.FILLED,
                "partial": OrderStatus.PARTIAL,
                "rejected": OrderStatus.REJECTED,
            }[status]
            updated.append(replace(order, status=order_status, reason=reason))
            return Fill(
                fill_id=fill_id,
                order_id=order.order_id,
                bar_index=bar_index,
                timestamp=frame.timestamp,
                symbol=order.symbol,
                quantity=quantity,
                price=price,
                commission=commission,
                slippage=slippage,
                cash_delta=cash_delta,
                status=status,
                reason=reason,
            )

        bar = frame.get(order.symbol)
        if bar is None:
            return record(0.0, 0.0, 0.0, 0.0, 0.0, "rejected", f"no bar for {order.symbol!r} at {frame.timestamp}")

        quantity = self._align(order.quantity)
        if quantity == 0:
            return record(0.0, 0.0, 0.0, 0.0, 0.0, "rejected", "quantity rounds to zero")
        side = 1 if quantity > 0 else -1
        base_price = bar.price(self._config.execution_price)
        price = base_price * (1 + side * self._config.slippage_rate)
        if price <= 0:
            return record(0.0, price, 0.0, 0.0, 0.0, "rejected", "non-positive execution price")
        status = "filled"
        reason = ""

        if side < 0 and not self._config.allow_short:
            available = account.position.quantity(order.symbol)
            if abs(quantity) > available + 1e-12:
                quantity = self._align(-min(abs(quantity), max(available, 0.0)))
                if quantity == 0:
                    return record(0.0, price, 0.0, 0.0, 0.0, "rejected", "insufficient position")
                status = "partial"
                reason = "trimmed to available position; remainder cancelled"

        gross = abs(quantity) * price
        commission = max(gross * self._config.commission_rate, self._config.min_commission)
        if side > 0 and gross + commission > account.cash + 1e-9:
            if self._config.reject_on_insufficient_cash:
                return record(
                    0.0, price, 0.0, 0.0, 0.0, "rejected",
                    "insufficient cash (reject_on_insufficient_cash=True)",
                )
            affordable = min(
                (account.cash - self._config.min_commission) / price,
                account.cash / (price * (1 + self._config.commission_rate)),
            )
            quantity = self._align(max(affordable, 0.0))
            if quantity == 0:
                return record(0.0, price, 0.0, 0.0, 0.0, "rejected", "no affordable quantity")
            gross = abs(quantity) * price
            commission = max(gross * self._config.commission_rate, self._config.min_commission)
            status = "partial"
            reason = "trimmed to available cash; remainder cancelled"

        slippage = abs(quantity) * abs(price - base_price)
        cash_delta = -(gross + commission) if side > 0 else gross - commission
        return record(quantity, price, commission, slippage, cash_delta, status, reason)
