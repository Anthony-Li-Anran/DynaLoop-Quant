"""Experiment metadata persistence contracts."""

from datetime import datetime
from typing import Protocol

from dynaloop.experiment_management.domain.models import (
    Experiment,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
)


class ExperimentRepository(Protocol):
    """Persist experiment definitions and immutable run history."""

    def create_experiment(self, experiment: Experiment) -> None:
        """Create an experiment without replacing an existing identity."""
        ...

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        """Return one experiment definition."""
        ...

    def list_experiments(self) -> tuple[Experiment, ...]:
        """Return experiments in stable identity order."""
        ...

    def update_experiment(self, experiment: Experiment) -> None:
        """Update only editable descriptive fields."""
        ...

    def create_run(self, run: ExperimentRun) -> None:
        """Create a pending run tied to an existing experiment."""
        ...

    def get_run(self, run_id: str) -> ExperimentRun | None:
        """Return one run."""
        ...

    def get_result(self, run_id: str) -> ExperimentResult | None:
        """Return the immutable result for a completed run."""
        ...

    def list_runs(self, experiment_id: str) -> tuple[ExperimentRun, ...]:
        """Return the experiment's run history in creation order."""
        ...

    def transition_run(
        self,
        run_id: str,
        status: ExperimentRunStatus,
        at: datetime,
        *,
        failure_message: str | None = None,
        result: ExperimentResult | None = None,
    ) -> ExperimentRun:
        """Validate and atomically persist one state transition and optional result."""
        ...
