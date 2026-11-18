"""Strategy base class and built-in examples.

Mature engines keep strategy logic in code objects; configuration only selects
a class and its kwargs (qlib workflow YAML ``{class, module_path, kwargs}``,
ml4t ``Strategy`` subclasses, backtrader ``cerebro.addstrategy(SmaCross)``).
The engine never parses a strategy expression from config.
"""

from __future__ import annotations

import importlib
from typing import Any, Mapping

from dynaloop.validation_backtesting_engine.domain.models import BacktestError


class BaseStrategy:
    """ml4t-style lifecycle: on_start -> on_prepare -> on_data* -> on_end."""

    def on_start(self, config: Any) -> None:
        pass

    def on_prepare(self, config: Any) -> None:
        """Receives resolved config only, never feed timestamps."""
        pass

    def on_data(self, timestamp: str, data: Any, context: Any, broker: Any) -> None:
        pass

    def on_end(self, result: Any) -> None:
        pass


class FlatStrategy(BaseStrategy):
    """No orders; useful as a deterministic control."""

    def __init__(self, **_: Any) -> None:
        pass


class BuyAndHoldStrategy(BaseStrategy):
    """Buy once at the first observable bar and hold."""

    def __init__(self, allocation: float = 0.95, symbol: str | None = None) -> None:
        if not 0 < allocation <= 1:
            raise BacktestError("allocation must be in (0, 1].")
        self.allocation = float(allocation)
        self.symbol = symbol
        self._submitted = False

    def on_start(self, config: Any) -> None:
        self._submitted = False

    def on_data(self, timestamp: str, data: Any, context: Any, broker: Any) -> None:
        if self._submitted:
            return
        symbol = self.symbol or (data.current.symbols()[0] if data.current.symbols() else None)
        bar = data.bar(symbol) if symbol else None
        if bar is None:
            return
        config = context.config
        buffer = 1 + config.commission_rate + config.slippage_rate
        quantity = broker.cash * self.allocation / (bar.close * buffer)
        if quantity > 0:
            broker.submit_order(symbol, quantity)
            self._submitted = True


class SmaCrossStrategy(BaseStrategy):
    """Fast/slow moving-average cross with full-in / full-out sizing."""

    def __init__(
        self,
        fast: int = 5,
        slow: int = 20,
        allocation: float = 0.95,
        symbol: str | None = None,
    ) -> None:
        if not 0 < fast < slow:
            raise BacktestError("SmaCross requires 0 < fast < slow.")
        if not 0 < allocation <= 1:
            raise BacktestError("allocation must be in (0, 1].")
        self.fast = int(fast)
        self.slow = int(slow)
        self.allocation = float(allocation)
        self.symbol = symbol

    @staticmethod
    def _mean(bars: tuple[Any, ...], length: int) -> float:
        window = bars[-length:]
        return sum(bar.close for bar in window) / len(window)

    def on_data(self, timestamp: str, data: Any, context: Any, broker: Any) -> None:
        symbol = self.symbol or (data.current.symbols()[0] if data.current.symbols() else None)
        if not symbol:
            return
        history = data.history(symbol)
        if len(history) < self.slow + 1:
            return
        current_fast = self._mean(history, self.fast)
        current_slow = self._mean(history, self.slow)
        previous = history[:-1]
        previous_fast = self._mean(previous, self.fast)
        previous_slow = self._mean(previous, self.slow)
        position = broker.positions.get(symbol, 0.0)

        if previous_fast <= previous_slow and current_fast > current_slow and position <= 0:
            buffer = 1 + context.config.commission_rate + context.config.slippage_rate
            quantity = broker.cash * self.allocation / (data.bar(symbol).close * buffer)
            broker.submit_order(symbol, quantity)
        elif previous_fast >= previous_slow and current_fast < current_slow and position > 0:
            broker.submit_order(symbol, -position)


class MomentumStrategy(BaseStrategy):
    """Time-series momentum: hold while the lookback return clears a threshold."""

    def __init__(
        self,
        lookback: int = 20,
        threshold: float = 0.0,
        allocation: float = 0.95,
        symbol: str | None = None,
    ) -> None:
        if lookback < 1:
            raise BacktestError("Momentum requires lookback >= 1.")
        if not 0 < allocation <= 1:
            raise BacktestError("allocation must be in (0, 1].")
        self.lookback = int(lookback)
        self.threshold = float(threshold)
        self.allocation = float(allocation)
        self.symbol = symbol

    def on_data(self, timestamp: str, data: Any, context: Any, broker: Any) -> None:
        symbol = self.symbol or (data.current.symbols()[0] if data.current.symbols() else None)
        if not symbol:
            return
        history = data.history(symbol)
        if len(history) < self.lookback + 1:
            return
        past = history[-self.lookback - 1].close
        if past <= 0:
            return
        momentum = history[-1].close / past - 1
        position = broker.positions.get(symbol, 0.0)
        bar = data.bar(symbol)
        if bar is None:
            return
        buffer = 1 + context.config.commission_rate + context.config.slippage_rate
        if momentum > self.threshold and position <= 0:
            broker.submit_order(symbol, broker.cash * self.allocation / (bar.close * buffer))
        elif momentum <= self.threshold and position > 0:
            broker.submit_order(symbol, -position)


class RsiReversionStrategy(BaseStrategy):
    """Buy oversold / sell overbought using a simple average-gain RSI."""

    def __init__(
        self,
        period: int = 14,
        lower: float = 30.0,
        upper: float = 70.0,
        allocation: float = 0.95,
        symbol: str | None = None,
    ) -> None:
        if period < 2 or not 0 < lower < upper < 100:
            raise BacktestError("RSI requires period >= 2 and 0 < lower < upper < 100.")
        if not 0 < allocation <= 1:
            raise BacktestError("allocation must be in (0, 1].")
        self.period = int(period)
        self.lower = float(lower)
        self.upper = float(upper)
        self.allocation = float(allocation)
        self.symbol = symbol

    def on_data(self, timestamp: str, data: Any, context: Any, broker: Any) -> None:
        symbol = self.symbol or (data.current.symbols()[0] if data.current.symbols() else None)
        if not symbol:
            return
        history = data.history(symbol)
        if len(history) < self.period + 1:
            return
        closes = [bar.close for bar in history[-(self.period + 1) :]]
        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = sum(max(change, 0.0) for change in changes) / len(changes)
        losses = sum(max(-change, 0.0) for change in changes) / len(changes)
        rsi = 100.0 if losses == 0 and gains > 0 else (
            50.0 if losses == 0 else 100.0 - 100.0 / (1.0 + gains / losses)
        )
        position = broker.positions.get(symbol, 0.0)
        bar = data.bar(symbol)
        if bar is None:
            return
        buffer = 1 + context.config.commission_rate + context.config.slippage_rate
        if rsi < self.lower and position <= 0:
            broker.submit_order(symbol, broker.cash * self.allocation / (bar.close * buffer))
        elif rsi > self.upper and position > 0:
            broker.submit_order(symbol, -position)


class DollarCostAveragingStrategy(BaseStrategy):
    """Fixed cash installment every N bars; holdings grow on each fill."""

    def __init__(
        self,
        interval: int = 10,
        amount: float = 10_000.0,
        symbol: str | None = None,
    ) -> None:
        if interval < 1 or amount <= 0:
            raise BacktestError("DCA requires interval >= 1 and amount > 0.")
        self.interval = int(interval)
        self.amount = float(amount)
        self.symbol = symbol

    def on_data(self, timestamp: str, data: Any, context: Any, broker: Any) -> None:
        if context.bar_index % self.interval != 0:
            return
        symbol = self.symbol or (data.current.symbols()[0] if data.current.symbols() else None)
        bar = data.bar(symbol) if symbol else None
        if bar is None:
            return
        buffer = 1 + context.config.commission_rate + context.config.slippage_rate
        budget = min(self.amount, broker.cash * 0.95 / buffer)
        if budget <= 0:
            return
        broker.submit_order(symbol, budget / (bar.close * buffer))


STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "Flat": FlatStrategy,
    "FlatStrategy": FlatStrategy,
    "BuyAndHold": BuyAndHoldStrategy,
    "BuyAndHoldStrategy": BuyAndHoldStrategy,
    "SmaCross": SmaCrossStrategy,
    "SmaCrossStrategy": SmaCrossStrategy,
    "Momentum": MomentumStrategy,
    "MomentumStrategy": MomentumStrategy,
    "RsiReversion": RsiReversionStrategy,
    "RsiReversionStrategy": RsiReversionStrategy,
    "DollarCostAveraging": DollarCostAveragingStrategy,
    "DollarCostAveragingStrategy": DollarCostAveragingStrategy,
}


# Presentation metadata for the "select a classic strategy" UI. Configuration
# only selects a class and its kwargs (qlib workflow YAML style); the JSON
# editor appears exclusively for the custom-strategy entry.
STRATEGY_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "class": "BuyAndHold",
        "label": "Buy & hold",
        "summary": "Buy once on the first bar and hold to the end. The baseline for every comparison.",
        "custom": False,
        "parameters": [
            {
                "key": "allocation",
                "label": "Capital to invest",
                "type": "number",
                "default": 0.95,
                "min": 0.1,
                "max": 1.0,
                "step": 0.05,
            }
        ],
    },
    {
        "class": "SmaCross",
        "label": "SMA crossover",
        "summary": "Golden cross buys, death cross sells. Full in / full out.",
        "custom": False,
        "parameters": [
            {"key": "fast", "label": "Fast window (bars)", "type": "integer", "default": 5, "min": 2, "max": 60, "step": 1},
            {"key": "slow", "label": "Slow window (bars)", "type": "integer", "default": 20, "min": 3, "max": 250, "step": 1},
            {"key": "allocation", "label": "Capital to invest", "type": "number", "default": 0.95, "min": 0.1, "max": 1.0, "step": 0.05},
        ],
    },
    {
        "class": "Momentum",
        "label": "Time-series momentum",
        "summary": "Hold while the lookback return is positive, otherwise stay in cash.",
        "custom": False,
        "parameters": [
            {"key": "lookback", "label": "Lookback (bars)", "type": "integer", "default": 20, "min": 2, "max": 120, "step": 1},
            {"key": "threshold", "label": "Return threshold", "type": "number", "default": 0.0, "min": -0.1, "max": 0.1, "step": 0.005},
        ],
    },
    {
        "class": "RsiReversion",
        "label": "RSI mean reversion",
        "summary": "Buy oversold, sell overbought using a simple RSI.",
        "custom": False,
        "parameters": [
            {"key": "period", "label": "RSI period", "type": "integer", "default": 14, "min": 2, "max": 60, "step": 1},
            {"key": "lower", "label": "Oversold level", "type": "number", "default": 30, "min": 5, "max": 49, "step": 1},
            {"key": "upper", "label": "Overbought level", "type": "number", "default": 70, "min": 51, "max": 95, "step": 1},
        ],
    },
    {
        "class": "DollarCostAveraging",
        "label": "Dollar-cost averaging",
        "summary": "A fixed cash installment every N bars; the position grows with each buy.",
        "custom": False,
        "parameters": [
            {"key": "interval", "label": "Buy every N bars", "type": "integer", "default": 10, "min": 1, "max": 60, "step": 1},
            {"key": "amount", "label": "Amount per buy (¥)", "type": "number", "default": 10000, "min": 1000, "max": 1000000, "step": 1000},
        ],
    },
    {
        "class": "__custom__",
        "label": "Custom strategy",
        "summary": "Provide a registry class or an importable module.Class path plus its kwargs as JSON.",
        "custom": True,
        "parameters": [],
    },
)


def get_strategy_catalog() -> tuple[dict[str, Any], ...]:
    return STRATEGY_CATALOG


def available_strategies() -> tuple[str, ...]:
    return tuple(sorted(STRATEGY_REGISTRY))


def build_strategy(spec: str, kwargs: Mapping[str, Any] | None = None) -> BaseStrategy:
    """Resolve a registry name or an importable ``module.Class`` path."""
    if not isinstance(spec, str) or not spec.strip():
        raise BacktestError("strategy_class must be a non-empty string.")
    name = spec.strip()
    parameters = dict(kwargs or {})
    if name in STRATEGY_REGISTRY:
        return STRATEGY_REGISTRY[name](**parameters)
    if "." in name:
        module_name, class_name = name.rsplit(".", 1)
        try:
            candidate = getattr(importlib.import_module(module_name), class_name)
            instance = candidate(**parameters)
        except (ImportError, AttributeError, TypeError) as exc:
            raise BacktestError(f"Cannot resolve strategy {name!r}: {exc}") from exc
        if not isinstance(instance, BaseStrategy):
            raise BacktestError(f"Strategy {name!r} must subclass BaseStrategy.")
        return instance
    raise BacktestError(
        f"Unknown strategy {name!r}. Available: {', '.join(available_strategies())} "
        "or an importable 'module.Class' path."
    )
