"""Stable entry point for recording and querying experiment history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from dynaloop.experiment_management.domain.models import (
    ArtifactReference,
    Experiment,
    ExperimentResult,
    ExperimentRun,
)
from dynaloop.experiment_management.services.lifecycle import (
    ExperimentLifecycleService,
)


class ExperimentManagementFacade:
    """Expose experiment metadata and run lifecycle without workload execution."""

    def __init__(self, service: ExperimentLifecycleService) -> None:
        self._service = service

    @classmethod
    def open_local(cls, database_path: str | Path) -> ExperimentManagementFacade:
        """Open a local SQLite-backed experiment history store."""
        from dynaloop.experiment_management.infrastructure.sqlite_repository import (
            SQLiteExperimentRepository,
        )

        return cls(ExperimentLifecycleService(SQLiteExperimentRepository(database_path)))

    def create_experiment(self, experiment: Experiment) -> Experiment:
        return self._service.create_experiment(experiment)

    def get_experiment(self, experiment_id: str) -> Experiment:
        return self._service.get_experiment(experiment_id)

    def list_experiments(self) -> tuple[Experiment, ...]:
        return self._service.list_experiments()

    def update_experiment(self, experiment: Experiment) -> Experiment:
        return self._service.update_experiment(experiment)

    def create_run(
        self,
        experiment_id: str,
        configuration_snapshot: Mapping[str, object],
        *,
        configuration_version: str | None = None,
        run_id: str | None = None,
        at: datetime | None = None,
    ) -> ExperimentRun:
        return self._service.create_run(
            experiment_id,
            configuration_snapshot,
            configuration_version=configuration_version,
            run_id=run_id,
            at=at,
        )

    def get_run(self, run_id: str) -> ExperimentRun:
        return self._service.get_run(run_id)

    def get_result(self, run_id: str) -> ExperimentResult | None:
        return self._service.get_result(run_id)

    def list_runs(self, experiment_id: str) -> tuple[ExperimentRun, ...]:
        return self._service.list_runs(experiment_id)

    def start_run(self, run_id: str, *, at: datetime | None = None) -> ExperimentRun:
        return self._service.start_run(run_id, at=at)

    def complete_run(
        self,
        run_id: str,
        metrics: tuple[tuple[str, int | float], ...] = (),
        artifacts: tuple[ArtifactReference, ...] = (),
        *,
        result_id: str | None = None,
        at: datetime | None = None,
    ) -> tuple[ExperimentRun, ExperimentResult]:
        return self._service.complete_run(
            run_id,
            metrics,
            artifacts,
            result_id=result_id,
            at=at,
        )

    def fail_run(
        self,
        run_id: str,
        failure_message: str,
        *,
        at: datetime | None = None,
    ) -> ExperimentRun:
        return self._service.fail_run(run_id, failure_message, at=at)

    def cancel_run(self, run_id: str, *, at: datetime | None = None) -> ExperimentRun:
        return self._service.cancel_run(run_id, at=at)
