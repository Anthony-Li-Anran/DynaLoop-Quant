"""Protocols following ml4t/backtest's lifecycle and qlib's loose coupling.

``on_prepare`` receives the resolved config only: no feed timestamps, so a
strategy cannot observe the future during preparation. ``on_data`` receives a
point-in-time ``BarView`` that the engine has already truncated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from dynaloop.validation_backtesting_engine.domain.models import BacktestConfig
    from dynaloop.validation_backtesting_engine.feed import BarView
    from dynaloop.validation_backtesting_engine.services.engine import StrategyContext
    from dynaloop.validation_backtesting_engine.services.report import BacktestResult


@runtime_checkable
class Strategy(Protocol):
    def on_start(self, config: "BacktestConfig") -> None: ...

    def on_prepare(self, config: "BacktestConfig") -> None: ...

    def on_data(
        self,
        timestamp: str,
        data: "BarView",
        context: "StrategyContext",
        broker: "Broker",
    ) -> None: ...

    def on_end(self, result: "BacktestResult") -> None: ...


@runtime_checkable
class DataFeed(Protocol):
    @property
    def frames(self) -> tuple[Any, ...]: ...

    @property
    def metadata(self) -> dict[str, Any]: ...

    def window(self, start: str | None = None, end: str | None = None) -> "DataFeed": ...


@runtime_checkable
class Broker(Protocol):
    def submit_order(self, symbol: str, quantity: float) -> Any: ...

    @property
    def cash(self) -> float: ...

    @property
    def positions(self) -> dict[str, float]: ...
