"""Factor signal -> buy / sell / not move, as an ordinary ``BaseStrategy``.

The factor column is materialised by the Research Engine (qlib DataHandler
style: columns are already computed, the handler only reads them). The strategy
therefore never recomputes a rolling window and never sees a future bar. It is
resolved through the engine's public ``build_strategy`` module.Class path, so
the backtest engine needs no change.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from dynaloop.validation_backtesting_engine.domain.models import BacktestError
from dynaloop.validation_backtesting_engine.strategies import BaseStrategy


class FactorSignalStrategy(BaseStrategy):
    """Trade a materialised factor column with the fixed three-action space.

    ``signals`` maps a bar timestamp to the factor value at that bar (``null``
    for NaN / warm-up). Long-flat holds when value > threshold; ``long_short``
    additionally opens a short, which requires ``BacktestConfig.allow_short``.
    """

    def __init__(
        self,
        signals: Mapping[str, Any],
        *,
        threshold: float = 0.0,
        allocation: float = 0.95,
        rule: str = "long_flat",
        symbol: str | None = None,
    ) -> None:
        if not isinstance(signals, Mapping):
            raise BacktestError("signals must be a timestamp -> value mapping.")
        if rule not in ("long_flat", "long_short"):
            raise BacktestError("rule must be 'long_flat' or 'long_short'.")
        if not 0 < allocation <= 1:
            raise BacktestError("allocation must be in (0, 1].")
        if not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)):
            raise BacktestError("threshold must be finite.")
        try:
            parsed = {
                str(timestamp): (None if value is None else float(value))
                for timestamp, value in signals.items()
            }
        except (TypeError, ValueError) as exc:
            raise BacktestError(f"Invalid factor signal value: {exc}") from exc
        for value in parsed.values():
            if value is not None and not math.isfinite(value):
                raise BacktestError("Factor signals must be finite or null.")
        self.signals = parsed
        self.threshold = float(threshold)
        self.allocation = float(allocation)
        self.rule = rule
        self.symbol = symbol

    def signal(self, timestamp: str) -> float | None:
        return self.signals.get(str(timestamp))

    def action(self, timestamp: str, position: float) -> str:
        """Pure decision function over the fixed buy / sell / not move space."""
        value = self.signal(timestamp)
        if value is None:
            return "not move"
        target = 1.0 if value > self.threshold else 0.0
        if self.rule == "long_short" and value < -self.threshold:
            target = -1.0
        if target > 0 and position < 0:
            return "buy"
        if target > 0 and position == 0:
            return "buy"
        if target < 0 and position == 0:
            return "sell"
        if target <= 0 and position > 0:
            return "sell"
        if target >= 0 and position < 0:
            return "buy"
        return "not move"

    def on_data(self, timestamp: str, data: Any, context: Any, broker: Any) -> None:
        symbol = self.symbol or (data.current.symbols()[0] if data.current.symbols() else None)
        if not symbol:
            return
        bar = data.bar(symbol)
        if bar is None:
            return
        position = broker.positions.get(symbol, 0.0)
        action = self.action(timestamp, position)
        if action == "not move":
            return
        buffer = 1 + context.config.commission_rate + context.config.slippage_rate
        if action == "buy":
            if position < 0:
                broker.submit_order(symbol, -position)
                return
            quantity = broker.cash * self.allocation / (bar.close * buffer)
            if quantity > 0:
                broker.submit_order(symbol, quantity)
            return
        if position > 0:
            broker.submit_order(symbol, -position)
            return
        if self.rule == "long_short":
            quantity = broker.cash * self.allocation / (bar.close * buffer)
            if quantity > 0:
                broker.submit_order(symbol, -quantity)
