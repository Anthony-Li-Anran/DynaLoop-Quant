"""Validation & Backtesting: an independent, self-contained backtest engine.

Layout follows ``microsoft/qlib``'s ``qlib/backtest`` split (executor /
exchange / account / position / decision / report); execution semantics and
the resolved-config / spec split follow ``ml4t/backtest``. The engine has its
own input contract and imports no other DynaLoop module's domain types.
"""

from dynaloop.validation_backtesting_engine.domain import (
    BacktestConfig,
    BacktestError,
    Bar,
    ExecutionMode,
    Fill,
    FillOrdering,
    Frame,
    Order,
    OrderStatus,
    PriceSource,
    ShareType,
)
from dynaloop.validation_backtesting_engine.facade import (
    backtest_from_records,
    run_backtest,
    run_saved_config,
)
from dynaloop.validation_backtesting_engine.feed import BarView, StaticFeed
from dynaloop.validation_backtesting_engine.interfaces import Broker, DataFeed, Strategy
from dynaloop.validation_backtesting_engine.results import RunResultStore
from dynaloop.validation_backtesting_engine.run_configs import (
    RunConfigError,
    RunConfigRecord,
    RunConfigStore,
    utc_now,
)
from dynaloop.validation_backtesting_engine.services import (
    Account,
    BacktestResult,
    Engine,
    Exchange,
    Position,
    StrategyContext,
    build_result,
)
from dynaloop.validation_backtesting_engine.strategies import (
    STRATEGY_CATALOG,
    STRATEGY_REGISTRY,
    BaseStrategy,
    BuyAndHoldStrategy,
    DollarCostAveragingStrategy,
    FlatStrategy,
    MomentumStrategy,
    RsiReversionStrategy,
    SmaCrossStrategy,
    available_strategies,
    build_strategy,
    get_strategy_catalog,
)

__all__ = [
    "Account",
    "BacktestConfig",
    "BacktestError",
    "BacktestResult",
    "Bar",
    "BarView",
    "BaseStrategy",
    "Broker",
    "BuyAndHoldStrategy",
    "DataFeed",
    "DollarCostAveragingStrategy",
    "Engine",
    "Exchange",
    "ExecutionMode",
    "Fill",
    "FillOrdering",
    "FlatStrategy",
    "Frame",
    "MomentumStrategy",
    "Order",
    "OrderStatus",
    "Position",
    "PriceSource",
    "RunConfigError",
    "RunConfigRecord",
    "RunConfigStore",
    "RunResultStore",
    "RsiReversionStrategy",
    "STRATEGY_CATALOG",
    "STRATEGY_REGISTRY",
    "ShareType",
    "SmaCrossStrategy",
    "StaticFeed",
    "Strategy",
    "StrategyContext",
    "available_strategies",
    "backtest_from_records",
    "build_result",
    "build_strategy",
    "get_strategy_catalog",
    "run_backtest",
    "run_saved_config",
    "utc_now",
]
