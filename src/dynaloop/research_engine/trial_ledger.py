"""Trial ledger: the complete, append-only record of a factor search.

The significance of a discovered factor cannot be interpreted without the
intensity of the search that produced it. The Deflated Sharpe Ratio needs the
number of independent trials N and the cross-trial Sharpe variance V; the
CSCV backtest-overfitting diagnostic needs the per-period returns of EVERY
configuration that was evaluated. Both must come from this ledger -- never
from an after-the-fact estimate of "how many things we probably tried".

Every evaluation is recorded, including failures, refuted candidates and
aborted configurations. Records are append-only: a trial cannot be edited or
removed once written, so the ledger cannot be quietly cleaned up to make the
search look smaller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

LEDGER_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """One evaluated configuration. ``returns_path`` points to its per-period
    returns so the CSCV matrix can be assembled without loading everything."""

    trial_id: str
    config_fingerprint: str
    segment: tuple[str, str]
    status: str  # evaluated | failed | refuted | aborted
    metrics: dict[str, Any] = field(default_factory=dict)
    returns_path: str | None = None
    cost_basis: str = "unknown"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "config_fingerprint": self.config_fingerprint,
            "segment": list(self.segment),
            "status": self.status,
            "metrics": self.metrics,
            "returns_path": self.returns_path,
            "cost_basis": self.cost_basis,
            "timestamp": self.timestamp,
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> "TrialRecord":
        return TrialRecord(
            trial_id=str(payload["trial_id"]),
            config_fingerprint=str(payload["config_fingerprint"]),
            segment=tuple(payload["segment"]),
            status=str(payload["status"]),
            metrics=dict(payload.get("metrics", {})),
            returns_path=payload.get("returns_path"),
            cost_basis=str(payload.get("cost_basis", "unknown")),
            timestamp=str(payload["timestamp"]),
            notes=str(payload.get("notes", "")),
        )


class TrialLedger:
    """Append-only collection of trial records with search-intensity views."""

    def __init__(self, records: Sequence[TrialRecord] | None = None) -> None:
        self._records: list[TrialRecord] = list(records or ())
        seen: set[str] = set()
        for record in self._records:
            if record.trial_id in seen:
                raise ValueError(f"duplicate trial_id: {record.trial_id}")
            seen.add(record.trial_id)

    def record(self, record: TrialRecord) -> TrialRecord:
        if any(existing.trial_id == record.trial_id for existing in self._records):
            raise ValueError(f"trial_id already recorded: {record.trial_id}")
        self._records.append(record)
        return record

    @property
    def records(self) -> tuple[TrialRecord, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)

    @property
    def n_trials(self) -> int:
        """Independent trial count N: every evaluated configuration counts,
        including failed and refuted ones (only aborted runs are excluded)."""
        return sum(1 for r in self._records if r.status != "aborted")

    def trial_sharpes(self, metric_key: str = "sharpe") -> np.ndarray:
        """Cross-trial Sharpe estimates used by the Deflated Sharpe Ratio."""
        values = [
            float(r.metrics[metric_key])
            for r in self._records
            if r.status != "aborted"
            and isinstance(r.metrics.get(metric_key), (int, float))
            and np.isfinite(float(r.metrics[metric_key]))
        ]
        return np.asarray(values, dtype=float)

    def sharpe_variance(self, metric_key: str = "sharpe") -> float:
        values = self.trial_sharpes(metric_key)
        if values.size < 2:
            raise ValueError("need at least two recorded Sharpe estimates")
        return float(values.var())

    def returns_matrix(self) -> np.ndarray:
        """Assemble the synchronous T x N matrix required by CSCV.

        Each trial's returns file stores a JSON list of per-period returns on
        the shared evaluation grid. Trials without a returns file cannot join
        the matrix; the caller decides whether that coverage is acceptable.
        """
        columns: list[np.ndarray] = []
        for record in self._records:
            if not record.returns_path:
                continue
            values = json.loads(Path(record.returns_path).read_text(encoding="utf-8"))
            columns.append(np.asarray(values, dtype=float))
        if not columns:
            raise ValueError("no trial returns available for the CSCV matrix")
        lengths = {c.size for c in columns}
        if len(lengths) != 1:
            raise ValueError("trial returns are not on a shared evaluation grid")
        return np.column_stack(columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "n_records": len(self._records),
            "n_independent_trials": self.n_trials,
            "records": [r.to_dict() for r in self._records],
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def load(path: str | Path) -> "TrialLedger":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise ValueError("unsupported trial ledger schema version")
        return TrialLedger([TrialRecord.from_dict(r) for r in payload["records"]])
