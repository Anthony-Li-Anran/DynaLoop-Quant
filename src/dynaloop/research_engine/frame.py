"""Frozen bar frame and materialised factor values.

qlib's ``DataHandler`` holds an already-materialised ``pd.DataFrame`` and its
``fetch`` / ``get_cols`` only select columns; expression evaluation belongs to
``ExpressionProvider``. This module keeps the same split: ``FactorFrame`` is the
read-only frame built from Data's raw records (source-declared columns only),
while ``evaluate_expression`` is the separate expression layer.
"""

from __future__ import annotations

import math
from numbers import Real
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from dynaloop.research_engine.expressions import (
    ExpressionEvaluationError,
    Node,
)
from dynaloop.research_engine.operators import evaluate_expression
from dynaloop.research_engine.spec import fingerprint


def _numeric(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, Real) and math.isnan(float(value)))


def _declared_names(columns: Sequence[Any] | None) -> tuple[str, ...] | None:
    """Accept both plain names and capability declarations (``{name: ...}``)."""
    if columns is None:
        return None
    names: list[str] = []
    for column in columns:
        if isinstance(column, str):
            names.append(column)
        elif isinstance(column, Mapping):
            for key in ("name", "key", "id", "column"):
                value = column.get(key)
                if isinstance(value, str):
                    names.append(value)
                    break
    return tuple(dict.fromkeys(names))


def window_records(
    records: Iterable[Mapping[str, Any]],
    *,
    start: str | None = None,
    end: str | None = None,
    timestamp_col: str = "date",
) -> list[dict[str, Any]]:
    """Freeze the run window using the same string comparison as StaticFeed."""
    rows: list[dict[str, Any]] = []
    for position, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ExpressionEvaluationError(f"Record {position} is not a mapping.")
        row = dict(record)
        if timestamp_col not in row:
            raise ExpressionEvaluationError(f"Record {position} is missing {timestamp_col!r}.")
        timestamp = str(row[timestamp_col])
        if (start not in (None, "") and timestamp < start) or (
            end not in (None, "") and timestamp > end
        ):
            continue
        rows.append(row)
    return rows


@dataclass(frozen=True, slots=True)
class FactorValues:
    """One materialised factor column, NaN kept as an explicit JSON-safe null."""

    expression: str
    timestamps: tuple[str, ...]
    values: tuple[float | None, ...]

    @classmethod
    def from_series(cls, series: pd.Series, expression: str) -> "FactorValues":
        timestamps = tuple(str(value) for value in series.index)
        values = tuple(
            None if value is None or not math.isfinite(float(value)) else float(value)
            for value in series.tolist()
        )
        return cls(expression=expression, timestamps=timestamps, values=values)

    def to_series(self) -> pd.Series:
        return pd.Series(
            [np.nan if value is None else value for value in self.values],
            index=pd.Index(self.timestamps, name="timestamp"),
            dtype=float,
            name=self.expression,
        )

    def signals(self) -> dict[str, float | None]:
        return dict(zip(self.timestamps, self.values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "expression": self.expression,
            "timestamps": list(self.timestamps),
            "values": list(self.values),
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


class FactorFrame:
    """Immutable numeric view over Data's raw bar records.

    Columns are the source's declared numeric columns. A column that the source
    did not provide is simply absent; no estimate, fill or substitution occurs.
    """

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        timestamp_col: str = "date",
        columns: Sequence[Any] | None = None,
    ) -> None:
        rows = list(records)
        if not rows:
            raise ExpressionEvaluationError("No bar records in the frozen window.")
        for position, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ExpressionEvaluationError(f"Record {position} is not a mapping.")
            if timestamp_col not in row:
                raise ExpressionEvaluationError(f"Record {position} is missing {timestamp_col!r}.")
        rows.sort(key=lambda row: str(row[timestamp_col]))
        timestamps = tuple(str(row[timestamp_col]) for row in rows)
        if len(set(timestamps)) != len(timestamps):
            raise ExpressionEvaluationError("Duplicate timestamps in the frozen window.")

        candidates = {
            key
            for row in rows
            for key, value in row.items()
            if key != timestamp_col and _numeric(value)
        }
        usable = sorted(
            key for key in candidates
            if all(_numeric(row.get(key)) or _missing(row.get(key)) for row in rows)
        )
        declared = _declared_names(columns)
        if declared is not None:
            usable = [key for key in usable if key in declared]
        if not usable:
            raise ExpressionEvaluationError("The dataset declares no numeric factor columns.")
        data = pd.DataFrame(
            [[np.nan if _missing(row.get(key)) else float(row[key]) for key in usable] for row in rows],
            index=pd.Index(timestamps, name="timestamp"),
            columns=pd.Index(usable),
            dtype=float,
        )
        self._data = data
        self._timestamps = timestamps
        self._declared_columns = declared
        self._timestamp_col = timestamp_col

    @property
    def data(self) -> pd.DataFrame:
        return self._data.copy(deep=True)

    @property
    def timestamps(self) -> tuple[str, ...]:
        return self._timestamps

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(str(column) for column in self._data.columns)

    @property
    def timestamp_col(self) -> str:
        return self._timestamp_col

    @property
    def declared_columns(self) -> tuple[str, ...] | None:
        return self._declared_columns

    def evaluate(self, node: Node, *, min_periods: int | None = 1) -> FactorValues:
        series = evaluate_expression(node, self._data, min_periods=min_periods)
        return FactorValues.from_series(series, str(node))

    def fingerprint(self) -> str:
        payload = [
            {"timestamp": timestamp, **{
                key: None if _missing(self._data.at[timestamp, key]) else float(self._data.at[timestamp, key])
                for key in self._data.columns
            }}
            for timestamp in self._timestamps
        ]
        return fingerprint({"columns": list(self.columns), "rows": payload})
