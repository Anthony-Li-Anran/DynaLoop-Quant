"""Immutable experiment definitions, run history, and structured results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite

from dynaloop.experiment_management.domain.errors import (
    ExperimentDefinitionError,
    ExperimentRunTransitionError,
)


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ExperimentDefinitionError(
            f"{field_name} must be a non-empty, trimmed string."
        )
    return value


def _optional_text(value: object, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ExperimentDefinitionError(
            f"{field_name} must be a timezone-aware datetime."
        )
    return value


class ExperimentRunStatus(Enum):
    """Lifecycle state for one experiment execution record."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Experiment:
    """Stable experiment identity and editable descriptive metadata."""

    experiment_id: str
    name: str
    description: str | None = None
    research_purpose: str | None = None
    configuration_reference: str | None = None
    configuration_version: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.experiment_id, "experiment_id")
        _require_text(self.name, "name")
        _optional_text(self.description, "description")
        _optional_text(self.research_purpose, "research_purpose")
        _optional_text(self.configuration_reference, "configuration_reference")
        _optional_text(self.configuration_version, "configuration_version")


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """Identity/version reference to an artifact owned by another module."""

    artifact_type: str
    artifact_id: str
    version: str

    def __post_init__(self) -> None:
        _require_text(self.artifact_type, "artifact_type")
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.version, "version")


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    """Immutable structured metrics and external artifact references for a run."""

    result_id: str
    run_id: str
    metrics: tuple[tuple[str, int | float], ...] = ()
    artifacts: tuple[ArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.result_id, "result_id")
        _require_text(self.run_id, "run_id")
        if not isinstance(self.metrics, (tuple, list)):
            raise ExperimentDefinitionError("metrics must be a sequence of pairs.")
        metrics: list[tuple[str, int | float]] = []
        seen: set[str] = set()
        for pair in self.metrics:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ExperimentDefinitionError("Each metric must be a name/value pair.")
            name, value = pair
            _require_text(name, "metric name")
            if name in seen:
                raise ExperimentDefinitionError(f"Duplicate metric '{name}'.")
            if type(value) not in (int, float) or (
                isinstance(value, float) and not isfinite(value)
            ):
                raise ExperimentDefinitionError(
                    f"Metric '{name}' must have a finite numeric value."
                )
            seen.add(name)
            metrics.append((name, value))
        if not isinstance(self.artifacts, (tuple, list)) or any(
            not isinstance(item, ArtifactReference) for item in self.artifacts
        ):
            raise ExperimentDefinitionError(
                "artifacts must contain ArtifactReference values."
            )
        object.__setattr__(self, "metrics", tuple(metrics))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    """One immutable-configuration execution record with validated transitions."""

    run_id: str
    experiment_id: str
    configuration_snapshot: str
    created_at: datetime
    status: ExperimentRunStatus = ExperimentRunStatus.PENDING
    configuration_version: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.experiment_id, "experiment_id")
        _require_aware(self.created_at, "created_at")
        _optional_text(self.configuration_version, "configuration_version")
        if not isinstance(self.status, ExperimentRunStatus):
            raise ExperimentDefinitionError("status must be an ExperimentRunStatus.")
        if not isinstance(self.configuration_snapshot, str):
            raise ExperimentDefinitionError("configuration_snapshot must be JSON text.")
        try:
            parsed = json.loads(self.configuration_snapshot)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ExperimentDefinitionError(
                "configuration_snapshot must contain a JSON object."
            ) from exc
        if not isinstance(parsed, dict):
            raise ExperimentDefinitionError(
                "configuration_snapshot must contain a JSON object."
            )
        if self.started_at is not None:
            _require_aware(self.started_at, "started_at")
        if self.finished_at is not None:
            _require_aware(self.finished_at, "finished_at")
        _optional_text(self.failure_message, "failure_message")

        if self.status is ExperimentRunStatus.PENDING:
            valid_timing = self.started_at is None and self.finished_at is None
            valid_failure = self.failure_message is None
        elif self.status is ExperimentRunStatus.RUNNING:
            valid_timing = self.started_at is not None and self.finished_at is None
            valid_failure = self.failure_message is None
        elif self.status is ExperimentRunStatus.COMPLETED:
            valid_timing = self.started_at is not None and self.finished_at is not None
            valid_failure = self.failure_message is None
        elif self.status is ExperimentRunStatus.FAILED:
            valid_timing = self.started_at is not None and self.finished_at is not None
            valid_failure = self.failure_message is not None
        else:
            valid_timing = self.finished_at is not None
            valid_failure = self.failure_message is None
        if not valid_timing or not valid_failure:
            raise ExperimentDefinitionError(
                f"Fields are inconsistent with {self.status.value} run status."
            )
        if (
            self.finished_at is not None
            and self.finished_at.astimezone(timezone.utc)
            < self.created_at.astimezone(timezone.utc)
        ):
            raise ExperimentDefinitionError("finished_at cannot precede created_at.")
        if (
            self.started_at is not None
            and self.started_at.astimezone(timezone.utc)
            < self.created_at.astimezone(timezone.utc)
        ):
            raise ExperimentDefinitionError("started_at cannot precede created_at.")
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at.astimezone(timezone.utc)
            < self.started_at.astimezone(timezone.utc)
        ):
            raise ExperimentDefinitionError("finished_at cannot precede started_at.")

    def transition(
        self,
        status: ExperimentRunStatus,
        at: datetime,
        *,
        failure_message: str | None = None,
        has_result: bool = False,
    ) -> ExperimentRun:
        """Return the next valid immutable run state."""
        _require_aware(at, "transition time")
        if not isinstance(status, ExperimentRunStatus):
            raise ExperimentDefinitionError("status must be an ExperimentRunStatus.")
        if at.astimezone(timezone.utc) < self.created_at.astimezone(timezone.utc):
            raise ExperimentDefinitionError("transition time cannot precede created_at.")
        allowed = {
            ExperimentRunStatus.PENDING: {
                ExperimentRunStatus.RUNNING,
                ExperimentRunStatus.CANCELLED,
            },
            ExperimentRunStatus.RUNNING: {
                ExperimentRunStatus.COMPLETED,
                ExperimentRunStatus.FAILED,
                ExperimentRunStatus.CANCELLED,
            },
        }
        if status not in allowed.get(self.status, set()):
            raise ExperimentRunTransitionError(
                f"Cannot transition run from {self.status.value} to {status.value}."
            )
        if status is ExperimentRunStatus.COMPLETED and not has_result:
            raise ExperimentDefinitionError("A completed run requires a result.")
        if status is ExperimentRunStatus.FAILED:
            _require_text(failure_message, "failure_message")
        elif failure_message is not None:
            raise ExperimentDefinitionError(
                "failure_message is only valid for a failed run."
            )

        started = (
            at
            if status is ExperimentRunStatus.RUNNING
            and self.status is ExperimentRunStatus.PENDING
            else self.started_at
        )
        return ExperimentRun(
            run_id=self.run_id,
            experiment_id=self.experiment_id,
            configuration_snapshot=self.configuration_snapshot,
            configuration_version=self.configuration_version,
            created_at=self.created_at,
            status=status,
            started_at=started,
            finished_at=(
                None if status is ExperimentRunStatus.RUNNING else at
            ),
            failure_message=failure_message,
        )
