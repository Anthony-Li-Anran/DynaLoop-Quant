"""Persistence for user-defined backtest run configurations.

This module owns only record storage. Timing, matching, accounting and
execution semantics belong to the engine core and are intentionally absent.
"""

from __future__ import annotations

from dynaloop.infrastructure import JsonMappingStore

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class RunConfigError(ValueError):
    """Raised when a submitted run configuration is malformed."""


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunConfigError(f"{label} must be a non-empty string.")
    return value.strip()


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise RunConfigError(f"{label} must map strings to values.")
    return dict(value)


@dataclass(frozen=True, slots=True)
class RunConfigRecord:
    """One saved, replayable description of a backtest the user wants to run.

    ``start`` / ``end`` are opaque caller-supplied window boundaries; this
    layer never interprets their units or enforces a trading calendar.
    ``strategy_kwargs``, ``execution`` and ``metadata`` are opaque JSON
    payloads so new engine knobs never require a storage migration.
    """

    config_id: str
    name: str
    dataset_id: str
    version_id: str
    symbol: str
    strategy_class: str
    start: str | None = None
    end: str | None = None
    initial_cash: float = 100_000.0
    strategy_kwargs: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.config_id, str) or not _ID_PATTERN.fullmatch(
            self.config_id
        ):
            raise RunConfigError(
                "Config ID must be lowercase letters, digits, '-' or '_'."
            )
        _require_text(self.name, "Name")
        _require_text(self.dataset_id, "Dataset ID")
        _require_text(self.version_id, "Version ID")
        _require_text(self.symbol, "Symbol")
        _require_text(self.strategy_class, "Strategy class")
        if self.start is not None:
            _require_text(self.start, "Start")
        if self.end is not None:
            _require_text(self.end, "End")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise RunConfigError("Start must not be after end.")
        if (
            not isinstance(self.initial_cash, (int, float))
            or isinstance(self.initial_cash, bool)
            or not math.isfinite(float(self.initial_cash))
            or float(self.initial_cash) <= 0
        ):
            raise RunConfigError("Initial cash must be a positive finite number.")
        _require_mapping(self.strategy_kwargs, "Strategy kwargs")
        _require_mapping(self.execution, "Execution settings")
        _require_mapping(self.metadata, "Metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "name": self.name,
            "dataset_id": self.dataset_id,
            "version_id": self.version_id,
            "symbol": self.symbol,
            "strategy_class": self.strategy_class,
            "start": self.start,
            "end": self.end,
            "initial_cash": self.initial_cash,
            "strategy_kwargs": dict(self.strategy_kwargs),
            "execution": dict(self.execution),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RunConfigRecord:
        return cls(
            config_id=str(payload.get("config_id", "")),
            name=str(payload.get("name", "")),
            dataset_id=str(payload.get("dataset_id", "")),
            version_id=str(payload.get("version_id", "")),
            symbol=str(payload.get("symbol", "")),
            strategy_class=str(payload.get("strategy_class", "")),
            start=payload.get("start"),
            end=payload.get("end"),
            initial_cash=float(payload.get("initial_cash", 100_000.0)),
            strategy_kwargs=dict(payload.get("strategy_kwargs") or {}),
            execution=dict(payload.get("execution") or {}),
            metadata=dict(payload.get("metadata") or {}),
            created_at=str(payload.get("created_at", "")),
        )

    def with_timestamp(self, created_at: str) -> RunConfigRecord:
        return RunConfigRecord(**{**self.to_dict(), "created_at": created_at})


class RunConfigStore:
    """JSON-file CRUD for saved run configurations."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._store = JsonMappingStore(path, error_type=RunConfigError, label='Stored run configurations', recover_invalid=False)

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, dict[str, Any]]:
        return self._store.read()

    def list_all(self) -> tuple[RunConfigRecord, ...]:
        return tuple(
            RunConfigRecord.from_dict(value)
            for _, value in sorted(self._read().items())
        )

    def get(self, config_id: str) -> RunConfigRecord | None:
        payload = self._read().get(config_id)
        return RunConfigRecord.from_dict(payload) if payload is not None else None

    def save(self, record: RunConfigRecord) -> None:
        with self._store.transaction() as entries:
            entries[record.config_id] = record.to_dict()

    def delete(self, config_id: str) -> bool:
        with self._store.transaction() as entries:
            if config_id not in entries:
                return False
            del entries[config_id]
        return True


def utc_now() -> str:
    """Stable ISO-8601 timestamp for record creation."""
    return datetime.now(timezone.utc).isoformat()
