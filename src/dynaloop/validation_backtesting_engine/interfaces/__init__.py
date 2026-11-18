"""Engine-facing protocols (loose coupling: components are replaceable)."""

from dynaloop.validation_backtesting_engine.interfaces.protocols import (
    Broker,
    DataFeed,
    Strategy,
)

__all__ = ["Broker", "DataFeed", "Strategy"]
