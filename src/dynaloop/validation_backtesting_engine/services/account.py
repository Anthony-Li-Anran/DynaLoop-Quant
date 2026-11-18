"""Account and position bookkeeping (qlib ``account`` / ``position`` split).

Fills update cash using the execution price source; equity is marked using a
separately configurable mark price source. The reconciliation identity
``cash + sum(position * mark) == equity`` is constructed to hold on every bar.
"""

from __future__ import annotations

from typing import Any

from dynaloop.validation_backtesting_engine.domain.models import (
    BacktestConfig,
    Fill,
    Frame,
    PriceSource,
)


class Position:
    """Quantities keyed by arbitrary symbols; no single-symbol constant."""

    def __init__(self) -> None:
        self._quantities: dict[str, float] = {}

    def quantity(self, symbol: str) -> float:
        return self._quantities.get(symbol, 0.0)

    def apply(self, symbol: str, quantity: float) -> None:
        updated = self.quantity(symbol) + quantity
        if abs(updated) < 1e-12:
            self._quantities.pop(symbol, None)
        else:
            self._quantities[symbol] = updated

    def as_dict(self) -> dict[str, float]:
        return {
            symbol: value
            for symbol, value in sorted(self._quantities.items())
            if abs(value) >= 1e-12
        }


class Account:
    """Cash ledger, positions, and mark-to-market equity per bar."""

    def __init__(self, config: BacktestConfig) -> None:
        self._cash = float(config.initial_cash)
        self._position = Position()
        self._marks: dict[str, float] = {}
        self._equity = self._cash

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def position(self) -> Position:
        return self._position

    @property
    def positions(self) -> dict[str, float]:
        return self._position.as_dict()

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def marks(self) -> dict[str, float]:
        return dict(sorted(self._marks.items()))

    def apply_fill(self, fill: Fill) -> None:
        if fill.status == "rejected" or fill.quantity == 0:
            return
        self._cash += fill.cash_delta
        self._position.apply(fill.symbol, fill.quantity)

    def mark_to_market(self, frame: Frame, source: PriceSource) -> None:
        for symbol, bar in frame.bars.items():
            self._marks[symbol] = bar.price(source)
        marked = sum(
            quantity * self._marks.get(symbol, 0.0)
            for symbol, quantity in self._position.as_dict().items()
        )
        self._equity = self._cash + marked

    def snapshot(self, bar_index: int, timestamp: str) -> dict[str, Any]:
        return {
            "bar_index": bar_index,
            "timestamp": timestamp,
            "cash": self._cash,
            "equity": self._equity,
            "positions": self.positions,
            "marks": self.marks,
        }

    def reconciliation_difference(self) -> float:
        marked = sum(
            quantity * self._marks.get(symbol, 0.0)
            for symbol, quantity in self._position.as_dict().items()
        )
        return self._cash + marked - self._equity
