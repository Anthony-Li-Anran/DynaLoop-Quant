"""SQLite persistence for experiments, runs, and immutable run results."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from dynaloop.experiment_management.domain.errors import (
    ExperimentDefinitionError,
    ExperimentIdentityConflictError,
    ExperimentNotFoundError,
    ExperimentRunConflictError,
)
from dynaloop.experiment_management.domain.models import (
    ArtifactReference,
    Experiment,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
)
from dynaloop.experiment_management.interfaces.protocols import ExperimentRepository


_FORMAT_VERSION = 1
_BUSY_TIMEOUT_SECONDS = 30


class SQLiteExperimentRepository(ExperimentRepository):
    """File-backed SQLite repository using short-lived, isolated connections."""

    def __init__(self, database_path: str | Path) -> None:
        if str(database_path) == ":memory:":
            raise ExperimentDefinitionError(
                "SQLiteExperimentRepository requires a file-backed database."
            )
        self._database_path = Path(database_path).expanduser().resolve()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    definition_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_runs (
                    run_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL
                        REFERENCES experiments(experiment_id),
                    created_at TEXT NOT NULL,
                    run_json TEXT NOT NULL,
                    result_json TEXT,
                    result_id TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS experiment_runs_history
                    ON experiment_runs(experiment_id, created_at, run_id);
                """
            )

    def create_experiment(self, experiment: Experiment) -> None:
        definition = _encode_experiment(experiment)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT definition_json FROM experiments WHERE experiment_id = ?",
                (experiment.experiment_id,),
            ).fetchone()
            if row is not None:
                if _decode_experiment(row["definition_json"]) != experiment:
                    raise ExperimentIdentityConflictError(
                        f"Experiment ID '{experiment.experiment_id}' already exists."
                    )
                raise ExperimentIdentityConflictError(
                    f"Experiment ID '{experiment.experiment_id}' already exists."
                )
            connection.execute(
                "INSERT INTO experiments (experiment_id, definition_json) VALUES (?, ?)",
                (experiment.experiment_id, definition),
            )

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT definition_json FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        return _decode_experiment(row["definition_json"]) if row else None

    def list_experiments(self) -> tuple[Experiment, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT definition_json FROM experiments ORDER BY experiment_id"
            ).fetchall()
        return tuple(_decode_experiment(row["definition_json"]) for row in rows)

    def update_experiment(self, experiment: Experiment) -> None:
        definition = _encode_experiment(experiment)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT definition_json FROM experiments WHERE experiment_id = ?",
                (experiment.experiment_id,),
            ).fetchone()
            if row is None:
                raise ExperimentNotFoundError(
                    f"Experiment '{experiment.experiment_id}' was not found."
                )
            existing = _decode_experiment(row["definition_json"])
            if (
                existing.configuration_reference != experiment.configuration_reference
                or existing.configuration_version != experiment.configuration_version
            ):
                raise ExperimentDefinitionError(
                    "Experiment configuration references cannot be changed by metadata update."
                )
            connection.execute(
                "UPDATE experiments SET definition_json = ? WHERE experiment_id = ?",
                (definition, experiment.experiment_id),
            )

    def create_run(self, run: ExperimentRun) -> None:
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO experiment_runs
                        (run_id, experiment_id, created_at, run_json, result_json)
                    VALUES (?, ?, ?, ?, NULL)
                    """,
                    (
                        run.run_id,
                        run.experiment_id,
                        run.created_at.isoformat(),
                        _encode_run(run),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                exists = connection.execute(
                    "SELECT 1 FROM experiment_runs WHERE run_id = ?",
                    (run.run_id,),
                ).fetchone()
                if exists is not None:
                    raise ExperimentRunConflictError(
                        f"Experiment run ID '{run.run_id}' already exists."
                    ) from exc
                parent = connection.execute(
                    "SELECT 1 FROM experiments WHERE experiment_id = ?",
                    (run.experiment_id,),
                ).fetchone()
                if parent is None:
                    raise ExperimentNotFoundError(
                        f"Experiment '{run.experiment_id}' was not found."
                    ) from exc
                raise

    def get_run(self, run_id: str) -> ExperimentRun | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT run_json FROM experiment_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return _decode_run(row["run_json"]) if row else None

    def get_result(self, run_id: str) -> ExperimentResult | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM experiment_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return _decode_result(row["result_json"]) if row["result_json"] else None

    def list_runs(self, experiment_id: str) -> tuple[ExperimentRun, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT run_json FROM experiment_runs
                WHERE experiment_id = ?
                ORDER BY julianday(created_at), run_id
                """,
                (experiment_id,),
            ).fetchall()
        return tuple(_decode_run(row["run_json"]) for row in rows)

    def transition_run(
        self,
        run_id: str,
        status: ExperimentRunStatus,
        at: datetime,
        *,
        failure_message: str | None = None,
        result: ExperimentResult | None = None,
    ) -> ExperimentRun:
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT run_json, result_json FROM experiment_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise ExperimentNotFoundError(f"Experiment run '{run_id}' was not found.")
            if row["result_json"] is not None:
                raise ExperimentRunConflictError(
                    f"Experiment run '{run_id}' already has an immutable result."
                )

            if status is ExperimentRunStatus.COMPLETED:
                if result is None or result.run_id != run_id:
                    raise ExperimentDefinitionError(
                        "A matching result is required to complete a run."
                    )
                encoded_result = _encode_result(result)
            elif result is not None:
                raise ExperimentDefinitionError(
                    "A result can only be recorded when completing a run."
                )
            else:
                encoded_result = None

            current = _decode_run(row["run_json"])
            updated = current.transition(
                status,
                at,
                failure_message=failure_message,
                has_result=result is not None,
            )
            try:
                connection.execute(
                    """
                    UPDATE experiment_runs
                    SET run_json = ?, result_json = ?, result_id = ?
                    WHERE run_id = ?
                    """,
                    (
                        _encode_run(updated),
                        encoded_result,
                        result.result_id if result is not None else None,
                        run_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if result is not None:
                    raise ExperimentRunConflictError(
                        f"Result ID '{result.result_id}' already exists."
                    ) from exc
                raise
            return updated

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(
            self._database_path,
            timeout=_BUSY_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute(
                f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_SECONDS * 1000}"
            )
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _pack(kind: str, value: dict[str, object]) -> str:
    return json.dumps(
        {"format_version": _FORMAT_VERSION, "kind": kind, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _unpack(raw: str, kind: str) -> dict[str, object]:
    try:
        envelope = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ExperimentDefinitionError("Stored experiment metadata is invalid.") from exc
    if (
        not isinstance(envelope, dict)
        or type(envelope.get("format_version")) is not int
        or envelope["format_version"] != _FORMAT_VERSION
        or envelope.get("kind") != kind
        or not isinstance(envelope.get("value"), dict)
    ):
        raise ExperimentDefinitionError(
            f"Stored {kind} metadata uses an unsupported format."
        )
    return envelope["value"]


def _encode_experiment(experiment: Experiment) -> str:
    return _pack(
        "Experiment",
        {
            "experiment_id": experiment.experiment_id,
            "name": experiment.name,
            "description": experiment.description,
            "research_purpose": experiment.research_purpose,
            "configuration_reference": experiment.configuration_reference,
            "configuration_version": experiment.configuration_version,
        },
    )


def _decode_experiment(raw: str) -> Experiment:
    value = _unpack(raw, "Experiment")
    return Experiment(
        experiment_id=_text(value, "experiment_id"),
        name=_text(value, "name"),
        description=_optional_text(value, "description"),
        research_purpose=_optional_text(value, "research_purpose"),
        configuration_reference=_optional_text(value, "configuration_reference"),
        configuration_version=_optional_text(value, "configuration_version"),
    )


def _encode_run(run: ExperimentRun) -> str:
    return _pack(
        "ExperimentRun",
        {
            "run_id": run.run_id,
            "experiment_id": run.experiment_id,
            "configuration_snapshot": run.configuration_snapshot,
            "configuration_version": run.configuration_version,
            "created_at": run.created_at.isoformat(),
            "status": run.status.value,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "failure_message": run.failure_message,
        },
    )


def _decode_run(raw: str) -> ExperimentRun:
    value = _unpack(raw, "ExperimentRun")
    return ExperimentRun(
        run_id=_text(value, "run_id"),
        experiment_id=_text(value, "experiment_id"),
        configuration_snapshot=_text(value, "configuration_snapshot"),
        configuration_version=_optional_text(value, "configuration_version"),
        created_at=datetime.fromisoformat(_text(value, "created_at")),
        status=ExperimentRunStatus(_text(value, "status")),
        started_at=_optional_datetime(value, "started_at"),
        finished_at=_optional_datetime(value, "finished_at"),
        failure_message=_optional_text(value, "failure_message"),
    )


def _encode_result(result: ExperimentResult) -> str:
    return _pack(
        "ExperimentResult",
        {
            "result_id": result.result_id,
            "run_id": result.run_id,
            "metrics": [[name, value] for name, value in result.metrics],
            "artifacts": [
                {
                    "artifact_type": artifact.artifact_type,
                    "artifact_id": artifact.artifact_id,
                    "version": artifact.version,
                }
                for artifact in result.artifacts
            ],
        },
    )


def _decode_result(raw: str) -> ExperimentResult:
    value = _unpack(raw, "ExperimentResult")
    metrics: list[tuple[str, int | float]] = []
    metric_values = value.get("metrics")
    if not isinstance(metric_values, list):
        raise ExperimentDefinitionError("Stored result metrics are invalid.")
    for pair in metric_values:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or type(pair[1]) not in (int, float)
        ):
            raise ExperimentDefinitionError("Stored result metric is invalid.")
        metrics.append((pair[0], pair[1]))
    artifact_values = value.get("artifacts")
    if not isinstance(artifact_values, list):
        raise ExperimentDefinitionError("Stored result artifacts are invalid.")
    artifacts: list[ArtifactReference] = []
    for artifact in artifact_values:
        if not isinstance(artifact, dict):
            raise ExperimentDefinitionError("Stored artifact reference is invalid.")
        artifacts.append(
            ArtifactReference(
                artifact_type=_text(artifact, "artifact_type"),
                artifact_id=_text(artifact, "artifact_id"),
                version=_text(artifact, "version"),
            )
        )
    return ExperimentResult(
        result_id=_text(value, "result_id"),
        run_id=_text(value, "run_id"),
        metrics=tuple(metrics),
        artifacts=tuple(artifacts),
    )


def _text(value: dict[str, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str):
        raise ExperimentDefinitionError(f"Stored field '{key}' must be text.")
    return raw


def _optional_text(value: dict[str, object], key: str) -> str | None:
    raw = value.get(key)
    if raw is not None and not isinstance(raw, str):
        raise ExperimentDefinitionError(f"Stored field '{key}' must be text or None.")
    return raw


def _optional_datetime(value: dict[str, object], key: str) -> datetime | None:
    raw = _optional_text(value, key)
    return datetime.fromisoformat(raw) if raw is not None else None
