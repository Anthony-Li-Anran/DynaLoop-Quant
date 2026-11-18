"""Coordinate experiment definitions and persisted run state transitions."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from dynaloop.experiment_management.domain.errors import (
    ExperimentDefinitionError,
    ExperimentNotFoundError,
)
from dynaloop.experiment_management.domain.models import (
    ArtifactReference,
    Experiment,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
)
from dynaloop.experiment_management.interfaces.protocols import ExperimentRepository


class ExperimentLifecycleService:
    """Create and query experiment runs without executing their workloads."""

    def __init__(self, repository: ExperimentRepository) -> None:
        self._repository = repository

    def create_experiment(self, experiment: Experiment) -> Experiment:
        self._repository.create_experiment(experiment)
        return experiment

    def get_experiment(self, experiment_id: str) -> Experiment:
        experiment = self._repository.get_experiment(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(
                f"Experiment '{experiment_id}' was not found."
            )
        return experiment

    def list_experiments(self) -> tuple[Experiment, ...]:
        return self._repository.list_experiments()

    def update_experiment(self, experiment: Experiment) -> Experiment:
        self._repository.update_experiment(experiment)
        return experiment

    def create_run(
        self,
        experiment_id: str,
        configuration_snapshot: Mapping[str, object],
        *,
        configuration_version: str | None = None,
        run_id: str | None = None,
        at: datetime | None = None,
    ) -> ExperimentRun:
        experiment = self.get_experiment(experiment_id)
        snapshot = _encode_configuration(configuration_snapshot)
        run = ExperimentRun(
            run_id=run_id or str(uuid.uuid4()),
            experiment_id=experiment_id,
            configuration_snapshot=snapshot,
            configuration_version=(
                configuration_version
                if configuration_version is not None
                else experiment.configuration_version
            ),
            created_at=at or datetime.now(timezone.utc),
        )
        self._repository.create_run(run)
        return run

    def get_run(self, run_id: str) -> ExperimentRun:
        run = self._repository.get_run(run_id)
        if run is None:
            raise ExperimentNotFoundError(f"Experiment run '{run_id}' was not found.")
        return run

    def get_result(self, run_id: str) -> ExperimentResult | None:
        self.get_run(run_id)
        return self._repository.get_result(run_id)

    def list_runs(self, experiment_id: str) -> tuple[ExperimentRun, ...]:
        self.get_experiment(experiment_id)
        return self._repository.list_runs(experiment_id)

    def start_run(self, run_id: str, *, at: datetime | None = None) -> ExperimentRun:
        return self._repository.transition_run(
            run_id,
            ExperimentRunStatus.RUNNING,
            at or datetime.now(timezone.utc),
        )

    def complete_run(
        self,
        run_id: str,
        metrics: tuple[tuple[str, int | float], ...] = (),
        artifacts: tuple[ArtifactReference, ...] = (),
        *,
        result_id: str | None = None,
        at: datetime | None = None,
    ) -> tuple[ExperimentRun, ExperimentResult]:
        result = ExperimentResult(
            result_id=result_id or str(uuid.uuid4()),
            run_id=run_id,
            metrics=metrics,
            artifacts=artifacts,
        )
        run = self._repository.transition_run(
            run_id,
            ExperimentRunStatus.COMPLETED,
            at or datetime.now(timezone.utc),
            result=result,
        )
        return run, result

    def fail_run(
        self,
        run_id: str,
        failure_message: str,
        *,
        at: datetime | None = None,
    ) -> ExperimentRun:
        return self._repository.transition_run(
            run_id,
            ExperimentRunStatus.FAILED,
            at or datetime.now(timezone.utc),
            failure_message=failure_message,
        )

    def cancel_run(self, run_id: str, *, at: datetime | None = None) -> ExperimentRun:
        return self._repository.transition_run(
            run_id,
            ExperimentRunStatus.CANCELLED,
            at or datetime.now(timezone.utc),
        )


def _encode_configuration(configuration: Mapping[str, object]) -> str:
    if not isinstance(configuration, Mapping):
        raise ExperimentDefinitionError(
            "configuration_snapshot must be a mapping."
        )
    try:
        normalized = _normalize_json_value(configuration)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ExperimentDefinitionError(
            "configuration_snapshot must contain JSON-compatible values."
        ) from exc
    if not isinstance(decoded, dict):
        raise ExperimentDefinitionError(
            "configuration_snapshot must encode a JSON object."
        )
    return encoded


def _normalize_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ExperimentDefinitionError(
                "Configuration object keys must be strings."
            )
        return {key: _normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ExperimentDefinitionError(
        "configuration_snapshot must contain JSON-compatible values."
    )
