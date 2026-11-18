"""Human final-decision records: audit trail, not an algorithm.

The architecture diagram places a Human Investor at the final decision node,
comparing subjective vs quantitative outputs. This module provides the record
mechanism only: a human records which side (if any) they chose, their rationale,
and the fingerprints of the two inputs they reviewed. It NEVER decides, scores,
ranks, or claims the choice was profitable or correct.

Storage is an atomic JSON mapping reused from infrastructure.JsonMappingStore;
each record is keyed by a generated id, so appending does not rewrite history.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dynaloop.infrastructure import JsonMappingStore, fingerprint

Choice = Literal["subjective", "quantitative", "both", "neither", "defer"]


class DecisionRecordError(ValueError):
    pass


class DecisionLedger:
    def __init__(self, path: str | Path) -> None:
        self._store = JsonMappingStore(
            path, error_type=DecisionRecordError,
            label="decision record store",
        )

    def record(
        self,
        *,
        choice: Choice,
        rationale: str,
        subjective_fingerprint: str | None,
        quantitative_fingerprint: str | None,
        decision_time: str | None = None,
    ) -> dict[str, Any]:
        if choice not in ("subjective", "quantitative", "both", "neither", "defer"):
            raise DecisionRecordError(f"unsupported choice: {choice!r}")
        if not rationale.strip():
            raise DecisionRecordError("rationale must be non-empty")
        record_id = uuid.uuid4().hex
        body = {
            "record_id": record_id,
            "choice": choice,
            "rationale": rationale.strip(),
            "subjective_fingerprint": subjective_fingerprint,
            "quantitative_fingerprint": quantitative_fingerprint,
            "decision_time": decision_time or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": "human-decision-record/1",
        }
        body["fingerprint"] = fingerprint(body)
        with self._store.transaction() as entries:
            entries[record_id] = body
        return body

    def list(self) -> list[dict[str, Any]]:
        return list(self._store.read().values())

    def get(self, record_id: str) -> dict[str, Any]:
        entries = self._store.read()
        if record_id not in entries:
            raise DecisionRecordError("record not found")
        return entries[record_id]


__all__ = ["Choice", "DecisionLedger", "DecisionRecordError"]
