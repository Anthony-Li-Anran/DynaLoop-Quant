"""Domain models for the backtest engine.

Responsibilities follow ``microsoft/qlib``'s ``qlib/backtest`` package
(account / position / exchange / decision) and the explicit execution knobs
documented by ``ml4t/backtest`` (``BacktestConfig``, ``ExecutionMode``,
``ExecutionPrice``, ``FillOrdering``, ``CommissionType``, ``SlippageType``).
The engine advances over an ordered sequence of frames and never interprets
the time unit of ``timestamp``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class BacktestError(ValueError):
    """Raised when engine inputs are invalid or a strategy cannot be resolved."""


class ExecutionMode(str, Enum):
    SAME_BAR = "same_bar"
    NEXT_BAR = "next_bar"


class PriceSource(str, Enum):
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    PRICE = "price"


class FillOrdering(str, Enum):
    EXIT_FIRST = "exit_first"
    FIFO = "fifo"
    SEQUENTIAL = "sequential"


class ShareType(str, Enum):
    INTEGER = "integer"
    FRACTIONAL = "fractional"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV observation for one symbol at one timestamp."""

    timestamp: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise BacktestError(f"Bar.{name} must be numeric.")
            if not math.isfinite(float(value)) or float(value) < 0:
                raise BacktestError(f"Bar.{name} must be finite and non-negative.")
        if float(self.close) <= 0:
            raise BacktestError("Bar.close must be positive.")
        if not isinstance(self.timestamp, str) or not self.timestamp:
            raise BacktestError("Bar.timestamp must be a non-empty string.")
        if not isinstance(self.symbol, str) or not self.symbol:
            raise BacktestError("Bar.symbol must be a non-empty string.")

    def price(self, source: PriceSource) -> float:
        # ml4t's PRICE source is the feed's canonical price column; here that
        # column is `close`. Fill and mark sources stay independently selectable.
        if source is PriceSource.PRICE:
            return float(self.close)
        return float(getattr(self, source.value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True, slots=True)
class Frame:
    """All symbols observed at one timestamp; symbols are an arbitrary set."""

    timestamp: str
    bars: Mapping[str, Bar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", MappingProxyType(dict(self.bars)))

    def get(self, symbol: str) -> Bar | None:
        return self.bars.get(symbol)

    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.bars))

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "bars": {key: value.to_dict() for key, value in sorted(self.bars.items())},
        }


@dataclass(frozen=True, slots=True)
class Order:
    """Signed quantity: positive buys, negative sells (qlib-style amount)."""

    order_id: str
    symbol: str
    quantity: float
    submitted_index: int
    eligible_index: int
    status: OrderStatus = OrderStatus.PENDING
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "submitted_index": self.submitted_index,
            "eligible_index": self.eligible_index,
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class Fill:
    """One execution attempt; rejected attempts are part of the audit ledger."""

    fill_id: str
    order_id: str
    bar_index: int
    timestamp: str
    symbol: str
    quantity: float
    price: float
    commission: float
    slippage: float
    cash_delta: float
    status: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "bar_index": self.bar_index,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "price": self.price,
            "commission": self.commission,
            "slippage": self.slippage,
            "cash_delta": self.cash_delta,
            "status": self.status,
            "reason": self.reason,
        }


_CONFIG_ENUMS: dict[str, type[Enum]] = {
    "execution_mode": ExecutionMode,
    "execution_price": PriceSource,
    "mark_price": PriceSource,
    "fill_ordering": FillOrdering,
    "share_type": ShareType,
}


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Resolved engine configuration; every default is expanded by ``to_dict``.

    The backtest window is deliberately NOT a field here. Following
    ``ml4t/backtest`` (``configuration.md``) and qlib's ``backtest(start_time,
    end_time)``, start/end are ``run()`` arguments; the realized window is a
    result recorded in the spec, not a configuration item.
    """

    initial_cash: float = 100_000.0
    execution_mode: ExecutionMode = ExecutionMode.NEXT_BAR
    execution_price: PriceSource = PriceSource.OPEN
    mark_price: PriceSource = PriceSource.CLOSE
    fill_ordering: FillOrdering = FillOrdering.EXIT_FIRST
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    slippage_rate: float = 0.0
    share_type: ShareType = ShareType.INTEGER
    lot_size: float = 1.0
    reject_on_insufficient_cash: bool = True
    allow_short: bool = False
    benchmark: str | None = "buy_and_hold"
    data_frequency: str | None = None
    calendar: str | None = None
    timezone: str | None = None
    periods_per_year: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "BacktestConfig":
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise BacktestError("BacktestConfig payload must be a mapping.")
        known = set(cls.__dataclass_fields__)
        unknown = set(payload) - known
        if unknown:
            raise BacktestError(
                f"Unknown BacktestConfig keys: {', '.join(sorted(unknown))}."
            )
        values: dict[str, Any] = {}
        for key, value in payload.items():
            if key in _CONFIG_ENUMS and not isinstance(value, _CONFIG_ENUMS[key]):
                try:
                    values[key] = _CONFIG_ENUMS[key](str(value).lower())
                except ValueError as exc:
                    raise BacktestError(f"Invalid value for {key}: {value!r}.") from exc
            else:
                values[key] = value
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        """Fully resolved config: every knob, including defaults, is explicit."""
        return {
            "initial_cash": self.initial_cash,
            "execution_mode": self.execution_mode.value,
            "execution_price": self.execution_price.value,
            "mark_price": self.mark_price.value,
            "fill_ordering": self.fill_ordering.value,
            "commission_rate": self.commission_rate,
            "min_commission": self.min_commission,
            "slippage_rate": self.slippage_rate,
            "share_type": self.share_type.value,
            "lot_size": self.lot_size,
            "reject_on_insufficient_cash": self.reject_on_insufficient_cash,
            "allow_short": self.allow_short,
            "benchmark": self.benchmark,
            "data_frequency": self.data_frequency,
            "calendar": self.calendar,
            "timezone": self.timezone,
            "periods_per_year": self.periods_per_year,
            "metadata": dict(self.metadata),
        }

    def validate(self) -> tuple[str, ...]:
        """Validate hard constraints and return non-fatal warnings."""
        if (
            not isinstance(self.initial_cash, (int, float))
            or not math.isfinite(float(self.initial_cash))
            or float(self.initial_cash) <= 0
        ):
            raise BacktestError("initial_cash must be a positive finite number.")
        for name in ("commission_rate", "min_commission", "slippage_rate"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise BacktestError(f"{name} must be a non-negative finite number.")
        if float(self.lot_size) <= 0:
            raise BacktestError("lot_size must be positive.")
        if self.slippage_rate >= 1:
            raise BacktestError("slippage_rate must be below 1.")
        warnings: list[str] = []
        if self.execution_mode is ExecutionMode.SAME_BAR:
            warnings.append(
                "SAME_BAR execution fills on the bar used for the decision; "
                "look-ahead bias is possible (ml4t/backtest validate() emits "
                "the same warning)."
            )
        if self.periods_per_year is None:
            warnings.append(
                "periods_per_year is unset, so annualized statistics are omitted; "
                "the engine does not assume a data frequency."
            )
        return tuple(warnings)
