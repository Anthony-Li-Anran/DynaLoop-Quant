"""SQLite-backed Dataset, DatasetVersion, and Snapshot repositories."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from dynaloop.data.domain.errors import (
    DataDefinitionError,
    DatasetIdentityConflictError,
    DatasetVersionCandidateNotFoundError,
    DatasetVersionCandidateStateError,
    DatasetVersionIdentityConflictError,
    DatasetVersionValidationError,
)
from dynaloop.data.domain.models import (
    AcquisitionMode,
    AcquisitionRecord,
    ContentReference,
    DataLayer,
    DataPartition,
    Dataset,
    DatasetSchema,
    DatasetSnapshot,
    DatasetVersion,
    DatasetVersionReference,
    DataSource,
    ProcessingLineage,
    QualityReport,
    QualityStatus,
    SchemaField,
    SnapshotPartitionSource,
    TemporalField,
    TemporalFieldRole,
)


_SCHEMA_VERSION = 2
_FORMAT_VERSION = 1
_BUSY_TIMEOUT_SECONDS = 30


class _SQLiteMetadataStore:
    """Persist all metadata with independent, short-lived SQLite connections.

    Every write transaction starts with ``BEGIN IMMEDIATE`` so the Head
    comparison and update execute under SQLite's cross-connection write lock.
    """

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()
        if str(database_path) == ":memory:":
            raise DataDefinitionError(
                "SQLiteMetadataRepository requires a file-backed database."
            )
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT definition_json FROM datasets WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
        if row is None:
            return None
        return _decode_dataset(row["definition_json"])

    def list_datasets(self) -> tuple[Dataset, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT definition_json FROM datasets ORDER BY dataset_id"
            ).fetchall()
        return tuple(_decode_dataset(row["definition_json"]) for row in rows)

    def register(self, dataset: Dataset) -> None:
        if not isinstance(dataset, Dataset):
            raise DataDefinitionError("dataset must be a Dataset.")
        definition = _encode_dataset(dataset)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT definition_json FROM datasets WHERE dataset_id = ?",
                (dataset.dataset_id,),
            ).fetchone()
            if row is not None:
                existing = _decode_dataset(row["definition_json"])
                if existing != dataset:
                    raise DatasetIdentityConflictError(
                        f"Dataset ID '{dataset.dataset_id}' already has another definition."
                    )
                return
            connection.execute(
                "INSERT INTO datasets (dataset_id, definition_json) VALUES (?, ?)",
                (dataset.dataset_id, definition),
            )

    def update_dataset(self, dataset: Dataset) -> None:
        """Replace only the descriptive definition of an existing dataset."""
        if not isinstance(dataset, Dataset):
            raise DataDefinitionError("dataset must be a Dataset.")
        definition = _encode_dataset(dataset)
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE datasets SET definition_json = ? WHERE dataset_id = ?",
                (definition, dataset.dataset_id),
            )
            if cursor.rowcount == 0:
                raise DataDefinitionError(
                    f"Dataset '{dataset.dataset_id}' was not found."
                )

    def archived_dataset_ids(self) -> tuple[str, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT dataset_id FROM dataset_archive ORDER BY dataset_id"
            ).fetchall()
        return tuple(str(row["dataset_id"]) for row in rows)

    def archive_dataset(self, dataset_id: str) -> None:
        """Hide a dataset from management views without deleting its bytes."""
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO dataset_archive (dataset_id) VALUES (?)",
                (dataset_id,),
            )

    def restore_dataset(self, dataset_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM dataset_archive WHERE dataset_id = ?", (dataset_id,)
            )

    def purge_dataset(
        self, dataset_id: str
    ) -> tuple[tuple[ContentReference, ...], int, int]:
        """Irreversibly delete one archived dataset inside a single transaction.

        Returns content objects that became unreferenced, the number of removed
        versions, and the number of removed auxiliary metadata records.
        """
        with self._connection() as connection:
            archived = connection.execute(
                "SELECT 1 FROM dataset_archive WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
            definition = connection.execute(
                "SELECT 1 FROM datasets WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
            if definition is None:
                raise DataNotFoundError(f"Dataset '{dataset_id}' was not found.")
            if archived is None:
                raise DataDefinitionError(
                    f"Dataset '{dataset_id}' must be archived before permanent deletion."
                )
            version_rows = connection.execute(
                "SELECT definition_json FROM dataset_versions WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchall()

        references: list[ContentReference] = []
        for row in version_rows:
            for partition in _decode_version(row["definition_json"]).partitions:
                if partition.content_reference is not None:
                    references.append(partition.content_reference)

        with self._transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM dataset_archive WHERE dataset_id = ?", (dataset_id,)
            ).fetchone() is None:
                raise DataDefinitionError(
                    f"Dataset '{dataset_id}' must be archived before permanent deletion."
                )
            blockers: list[str] = []
            for table, key in (
                ("dataset_snapshots", "snapshot_id"),
                ("processing_lineages", "lineage_id"),
            ):
                for record in connection.execute(
                    f"SELECT {key}, definition_json FROM {table}"
                ).fetchall():
                    if _mentions_dataset(record["definition_json"], dataset_id):
                        blockers.append(f"{table}/{record[key]}")
            if blockers:
                raise DataDefinitionError(
                    "Dataset is still referenced by snapshots or lineages: "
                    + ", ".join(blockers)
                )

            # dataset_heads has a RESTRICT foreign key onto dataset_versions.
            connection.execute(
                "DELETE FROM dataset_heads WHERE dataset_id = ?", (dataset_id,)
            )
            deleted_versions = connection.execute(
                "DELETE FROM dataset_versions WHERE dataset_id = ?", (dataset_id,)
            ).rowcount
            connection.execute(
                "DELETE FROM dataset_archive WHERE dataset_id = ?", (dataset_id,)
            )
            connection.execute("DELETE FROM datasets WHERE dataset_id = ?", (dataset_id,))

            deleted_metadata = 0
            for table, key in (
                ("quality_reports", "report_id"),
                ("acquisition_records", "acquisition_id"),
            ):
                for record in connection.execute(
                    f"SELECT {key}, definition_json FROM {table}"
                ).fetchall():
                    if _mentions_dataset(record["definition_json"], dataset_id):
                        connection.execute(
                            f"DELETE FROM {table} WHERE {key} = ?", (record[key],)
                        )
                        deleted_metadata += 1

            # Content is addressed by hash and may be shared. Only objects with
            # no surviving version reference are safe to remove from disk.
            orphans: list[ContentReference] = []
            seen: set[str] = set()
            for reference in references:
                if reference.storage_key in seen:
                    continue
                seen.add(reference.storage_key)
                still_used = connection.execute(
                    "SELECT 1 FROM dataset_versions WHERE definition_json LIKE ? LIMIT 1",
                    (f"%{reference.storage_key}%",),
                ).fetchone()
                if still_used is None:
                    orphans.append(reference)
        return tuple(orphans), deleted_versions, deleted_metadata

    def get_source(self, source_id: str) -> DataSource | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT definition_json FROM data_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        return _decode_source(row["definition_json"]) if row else None

    def list_sources(self) -> tuple[DataSource, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT definition_json FROM data_sources ORDER BY source_id"
            ).fetchall()
        return tuple(_decode_source(row["definition_json"]) for row in rows)

    def register_source(self, source: DataSource) -> None:
        definition = _encode_source(source)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT definition_json FROM data_sources WHERE source_id = ?",
                (source.source_id,),
            ).fetchone()
            if row:
                if _decode_source(row["definition_json"]) != source:
                    raise DataDefinitionError(
                        f"Data source '{source.source_id}' has another definition."
                    )
                return
            connection.execute(
                "INSERT INTO data_sources (source_id, definition_json) VALUES (?, ?)",
                (source.source_id, definition),
            )

    def get_schema(self, schema_id: str, version: str) -> DatasetSchema | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT definition_json FROM dataset_schemas
                WHERE schema_id = ? AND version = ?
                """,
                (schema_id, version),
            ).fetchone()
        return _decode_schema(row["definition_json"]) if row else None

    def register_schema(self, schema: DatasetSchema) -> None:
        definition = _encode_schema(schema)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT definition_json FROM dataset_schemas
                WHERE schema_id = ? AND version = ?
                """,
                (schema.schema_id, schema.version),
            ).fetchone()
            if row:
                if _decode_schema(row["definition_json"]) != schema:
                    raise DataDefinitionError(
                        f"Schema '{schema.schema_id}@{schema.version}' "
                        "has another definition."
                    )
                return
            connection.execute(
                """
                INSERT INTO dataset_schemas (schema_id, version, definition_json)
                VALUES (?, ?, ?)
                """,
                (schema.schema_id, schema.version, definition),
            )

    def get_lineage(self, lineage_id: str) -> ProcessingLineage | None:
        return self._get_immutable_record(
            "processing_lineages", "lineage_id", lineage_id, _decode_lineage
        )

    def list_lineages(self) -> tuple[ProcessingLineage, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT definition_json FROM processing_lineages
                ORDER BY lineage_id
                """
            ).fetchall()
        return tuple(_decode_lineage(row["definition_json"]) for row in rows)

    def save_lineage(self, lineage: ProcessingLineage) -> None:
        with self._transaction() as connection:
            self._require_published_versions(
                connection,
                (*lineage.input_versions, *lineage.output_versions),
            )
            self._save_record_in_transaction(
                connection,
                "processing_lineages",
                "lineage_id",
                lineage.lineage_id,
                _encode_lineage(lineage),
                _decode_lineage,
                lineage,
            )

    def get_quality_report(self, report_id: str) -> QualityReport | None:
        return self._get_immutable_record(
            "quality_reports", "report_id", report_id, _decode_quality_report
        )

    def list_quality_reports(self) -> tuple[QualityReport, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT definition_json FROM quality_reports ORDER BY report_id"
            ).fetchall()
        return tuple(_decode_quality_report(row["definition_json"]) for row in rows)

    def save_quality_report(self, report: QualityReport) -> None:
        with self._transaction() as connection:
            self._require_published_versions(connection, (report.dataset_version,))
            self._save_record_in_transaction(
                connection,
                "quality_reports",
                "report_id",
                report.report_id,
                _encode_quality_report(report),
                _decode_quality_report,
                report,
            )

    def get_acquisition(self, acquisition_id: str) -> AcquisitionRecord | None:
        return self._get_immutable_record(
            "acquisition_records",
            "acquisition_id",
            acquisition_id,
            _decode_acquisition,
        )

    def save_acquisition(self, record: AcquisitionRecord) -> None:
        with self._transaction() as connection:
            source = connection.execute(
                "SELECT 1 FROM data_sources WHERE source_id = ?",
                (record.source_id,),
            ).fetchone()
            if source is None:
                raise DataDefinitionError(
                    f"Acquisition source '{record.source_id}' is not registered."
                )
            published = connection.execute(
                """
                SELECT 1 FROM dataset_versions
                WHERE dataset_id = ? AND version_id = ? AND status = 'published'
                """,
                (
                    record.dataset_version.dataset_id,
                    record.dataset_version.version_id,
                ),
            ).fetchone()
            if published is None:
                raise DatasetVersionCandidateNotFoundError(
                    f"Acquisition version {record.dataset_version!r} is not published."
                )
            self._save_record_in_transaction(
                connection,
                "acquisition_records",
                "acquisition_id",
                record.acquisition_id,
                _encode_acquisition(record),
                _decode_acquisition,
                record,
            )

    def _get_immutable_record(self, table, key_column, key_value, decoder):
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT definition_json FROM {table} WHERE {key_column} = ?",
                (key_value,),
            ).fetchone()
        return decoder(row["definition_json"]) if row else None

    def _save_immutable_record(
        self,
        table,
        key_column,
        key_value,
        definition,
        decoder,
        value,
    ) -> None:
        with self._transaction() as connection:
            self._save_record_in_transaction(
                connection,
                table,
                key_column,
                key_value,
                definition,
                decoder,
                value,
            )

    @staticmethod
    def _require_published_versions(connection, references) -> None:
        for reference in references:
            row = connection.execute(
                """
                SELECT 1 FROM dataset_versions
                WHERE dataset_id = ? AND version_id = ? AND status = 'published'
                """,
                (reference.dataset_id, reference.version_id),
            ).fetchone()
            if row is None:
                raise DatasetVersionCandidateNotFoundError(
                    f"Metadata version {reference!r} is not published."
                )

    @staticmethod
    def _save_record_in_transaction(
        connection,
        table,
        key_column,
        key_value,
        definition,
        decoder,
        value,
    ) -> None:
        row = connection.execute(
            f"SELECT definition_json FROM {table} WHERE {key_column} = ?",
            (key_value,),
        ).fetchone()
        if row:
            if decoder(row["definition_json"]) != value:
                raise DataDefinitionError(
                    f"Metadata identity '{key_value}' has another definition."
                )
            return
        connection.execute(
            f"INSERT INTO {table} ({key_column}, definition_json) VALUES (?, ?)",
            (key_value, definition),
        )

    def get_version(
        self,
        reference: DatasetVersionReference,
    ) -> DatasetVersion | None:
        if not isinstance(reference, DatasetVersionReference):
            raise DataDefinitionError("reference must be a DatasetVersionReference.")
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT definition_json FROM dataset_versions
                WHERE dataset_id = ? AND version_id = ? AND status = 'published'
                """,
                (reference.dataset_id, reference.version_id),
            ).fetchone()
        if row is None:
            return None
        return _decode_version(row["definition_json"])

    def list_versions(self, dataset_id: str) -> tuple[DatasetVersion, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT definition_json FROM dataset_versions
                WHERE dataset_id = ? AND status = 'published'
                ORDER BY version_id
                """,
                (dataset_id,),
            ).fetchall()
        versions = tuple(_decode_version(row["definition_json"]) for row in rows)
        return tuple(
            sorted(
                versions,
                key=lambda version: (
                    version.created_at.astimezone(timezone.utc),
                    version.version_id,
                ),
            )
        )

    def get_head(self, dataset_id: str) -> DatasetVersionReference | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT h.version_id, v.status
                FROM dataset_heads AS h
                LEFT JOIN dataset_versions AS v
                  ON v.dataset_id = h.dataset_id AND v.version_id = h.version_id
                WHERE h.dataset_id = ?
                """,
                (dataset_id,),
            ).fetchone()
        if row is None:
            return None
        if row["status"] != "published":
            raise DataDefinitionError(
                f"Stored Head for dataset '{dataset_id}' does not reference a published version."
            )
        return DatasetVersionReference(dataset_id, row["version_id"])

    def save_candidate(self, version: DatasetVersion) -> None:
        if not isinstance(version, DatasetVersion):
            raise DataDefinitionError("version must be a DatasetVersion.")
        if any(partition.content_reference is None for partition in version.partitions):
            raise DatasetVersionValidationError(
                "Candidate versions must have a ContentReference for every partition."
            )
        definition = _encode_version(version)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT definition_json, status FROM dataset_versions
                WHERE dataset_id = ? AND version_id = ?
                """,
                (version.dataset_id, version.version_id),
            ).fetchone()
            if row is not None:
                existing = _decode_version(row["definition_json"])
                if existing != version:
                    raise DatasetVersionIdentityConflictError(
                        f"Version reference {version.reference!r} already has another definition."
                    )
                if row["status"] == "published":
                    raise DatasetVersionCandidateStateError(
                        f"Version {version.reference!r} is already published."
                    )
                return
            connection.execute(
                """
                INSERT INTO dataset_versions
                    (dataset_id, version_id, definition_json, status)
                VALUES (?, ?, ?, 'candidate')
                """,
                (version.dataset_id, version.version_id, definition),
            )

    def publish_candidate(
        self,
        reference: DatasetVersionReference,
        expected_head: DatasetVersionReference | None,
    ) -> bool:
        if not isinstance(reference, DatasetVersionReference):
            raise DataDefinitionError("reference must be a DatasetVersionReference.")
        if expected_head is not None and (
            not isinstance(expected_head, DatasetVersionReference)
            or expected_head.dataset_id != reference.dataset_id
        ):
            raise DataDefinitionError(
                "expected_head must belong to the candidate dataset."
            )

        with self._transaction() as connection:
            candidate = connection.execute(
                """
                SELECT status FROM dataset_versions
                WHERE dataset_id = ? AND version_id = ?
                """,
                (reference.dataset_id, reference.version_id),
            ).fetchone()
            if candidate is None:
                raise DatasetVersionCandidateNotFoundError(
                    f"Candidate version {reference!r} was not found."
                )
            if candidate["status"] != "candidate":
                raise DatasetVersionCandidateStateError(
                    f"Version {reference!r} is no longer a publishable candidate."
                )

            head = connection.execute(
                "SELECT version_id FROM dataset_heads WHERE dataset_id = ?",
                (reference.dataset_id,),
            ).fetchone()
            actual_head = (
                DatasetVersionReference(reference.dataset_id, head["version_id"])
                if head is not None
                else None
            )
            if actual_head != expected_head:
                return False

            updated = connection.execute(
                """
                UPDATE dataset_versions SET status = 'published'
                WHERE dataset_id = ? AND version_id = ? AND status = 'candidate'
                """,
                (reference.dataset_id, reference.version_id),
            )
            if updated.rowcount != 1:
                raise DatasetVersionCandidateStateError(
                    f"Version {reference!r} is no longer a publishable candidate."
                )
            connection.execute(
                """
                INSERT INTO dataset_heads (dataset_id, version_id)
                VALUES (?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET version_id = excluded.version_id
                """,
                (reference.dataset_id, reference.version_id),
            )
            return True

    def retract_version(
        self,
        reference: DatasetVersionReference,
        *,
        restore_head: DatasetVersionReference | None,
    ) -> bool:
        if not isinstance(reference, DatasetVersionReference):
            raise DataDefinitionError("reference must be a DatasetVersionReference.")
        if restore_head is not None and (
            not isinstance(restore_head, DatasetVersionReference)
            or restore_head.dataset_id != reference.dataset_id
        ):
            raise DataDefinitionError(
                "restore_head must belong to the retracted version's dataset."
            )

        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT status FROM dataset_versions
                WHERE dataset_id = ? AND version_id = ?
                """,
                (reference.dataset_id, reference.version_id),
            ).fetchone()
            if row is None or row["status"] != "published":
                return False

            head = connection.execute(
                "SELECT version_id FROM dataset_heads WHERE dataset_id = ?",
                (reference.dataset_id,),
            ).fetchone()
            if head is not None and head["version_id"] == reference.version_id:
                if restore_head is None:
                    connection.execute(
                        "DELETE FROM dataset_heads WHERE dataset_id = ?",
                        (reference.dataset_id,),
                    )
                else:
                    restored = connection.execute(
                        """
                        SELECT status FROM dataset_versions
                        WHERE dataset_id = ? AND version_id = ?
                        """,
                        (restore_head.dataset_id, restore_head.version_id),
                    ).fetchone()
                    if restored is None or restored["status"] != "published":
                        raise DatasetVersionCandidateStateError(
                            f"restore_head {restore_head!r} is not a published version."
                        )
                    connection.execute(
                        """
                        INSERT INTO dataset_heads (dataset_id, version_id)
                        VALUES (?, ?)
                        ON CONFLICT(dataset_id) DO UPDATE SET version_id = excluded.version_id
                        """,
                        (restore_head.dataset_id, restore_head.version_id),
                    )

            deleted = connection.execute(
                """
                DELETE FROM dataset_versions
                WHERE dataset_id = ? AND version_id = ? AND status = 'published'
                """,
                (reference.dataset_id, reference.version_id),
            )
            if deleted.rowcount != 1:
                return False
            return True

    def get_snapshot(self, snapshot_id: str) -> DatasetSnapshot | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT definition_json FROM dataset_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return _decode_snapshot(row["definition_json"])

    def list_snapshots(self) -> tuple[DatasetSnapshot, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT definition_json FROM dataset_snapshots ORDER BY snapshot_id"
            ).fetchall()
        return tuple(_decode_snapshot(row["definition_json"]) for row in rows)

    def save_snapshot(self, snapshot: DatasetSnapshot) -> None:
        if not isinstance(snapshot, DatasetSnapshot):
            raise DataDefinitionError("snapshot must be a DatasetSnapshot.")
        definition = _encode_snapshot(snapshot)
        with self._transaction() as connection:
            versions: list[DatasetVersion] = []
            for reference in snapshot.members:
                row = connection.execute(
                    """
                    SELECT definition_json FROM dataset_versions
                    WHERE dataset_id = ? AND version_id = ? AND status = 'published'
                    """,
                    (reference.dataset_id, reference.version_id),
                ).fetchone()
                if row is None:
                    raise DatasetVersionCandidateNotFoundError(
                        f"Snapshot member {reference!r} is not published."
                    )
                versions.append(_decode_version(row["definition_json"]))
            snapshot.validate_members(tuple(versions))

            existing = connection.execute(
                "SELECT definition_json FROM dataset_snapshots WHERE snapshot_id = ?",
                (snapshot.snapshot_id,),
            ).fetchone()
            if existing is not None:
                if _decode_snapshot(existing["definition_json"]) != snapshot:
                    raise DataDefinitionError(
                        f"Snapshot ID '{snapshot.snapshot_id}' already has another definition."
                    )
                return
            connection.execute(
                """
                INSERT INTO dataset_snapshots (snapshot_id, definition_json)
                VALUES (?, ?)
                """,
                (snapshot.snapshot_id, definition),
            )

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(
            self._database_path,
            timeout=_BUSY_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_SECONDS * 1000}"
            )
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

    def _initialize_schema(self) -> None:
        with self._transaction() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, _SCHEMA_VERSION):
                raise DataDefinitionError(
                    f"SQLite schema version {version} is not supported."
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    definition_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_archive (
                    dataset_id TEXT PRIMARY KEY
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_versions (
                    dataset_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('candidate', 'published')),
                    PRIMARY KEY (dataset_id, version_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_heads (
                    dataset_id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL,
                    FOREIGN KEY (dataset_id, version_id)
                        REFERENCES dataset_versions(dataset_id, version_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    definition_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS data_sources (
                    source_id TEXT PRIMARY KEY,
                    definition_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_schemas (
                    schema_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    PRIMARY KEY (schema_id, version)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_lineages (
                    lineage_id TEXT PRIMARY KEY,
                    definition_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS quality_reports (
                    report_id TEXT PRIMARY KEY,
                    definition_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS acquisition_records (
                    acquisition_id TEXT PRIMARY KEY,
                    definition_json TEXT NOT NULL
                )
                """
            )
            connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


def _pack(kind: str, payload: dict[str, object]) -> str:
    return json.dumps(
        {"format_version": _FORMAT_VERSION, "kind": kind, "value": payload},
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _unpack(raw: str, kind: str) -> dict[str, object]:
    try:
        envelope = json.loads(raw)
        if (
            not isinstance(envelope, dict)
            or type(envelope.get("format_version")) is not int
            or envelope["format_version"] != _FORMAT_VERSION
            or envelope.get("kind") != kind
            or not isinstance(envelope.get("value"), dict)
        ):
            raise ValueError("unsupported or malformed metadata envelope")
        return envelope["value"]
    except (TypeError, ValueError) as exc:
        raise DataDefinitionError(
            f"Stored {kind} metadata is invalid or uses an unsupported format."
        ) from exc


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("datetime metadata must be a string")
    return datetime.fromisoformat(value)


def _reference_value(reference: DatasetVersionReference | None) -> object:
    if reference is None:
        return None
    return {"dataset_id": reference.dataset_id, "version_id": reference.version_id}


def _parse_reference(value: object) -> DatasetVersionReference | None:
    if value is None:
        return None
    reference = _as_object(value)
    return DatasetVersionReference(
        _string_field(reference, "dataset_id"),
        _string_field(reference, "version_id"),
    )


def _content_reference_value(reference: ContentReference | None) -> object:
    if reference is None:
        return None
    return {
        "backend_id": reference.backend_id,
        "storage_key": reference.storage_key,
        "hash_algorithm": reference.hash_algorithm,
        "content_hash": reference.content_hash,
        "size_bytes": reference.size_bytes,
    }


def _parse_content_reference(value: object) -> ContentReference | None:
    if value is None:
        return None
    reference = _as_object(value)
    return ContentReference(
        backend_id=_string_field(reference, "backend_id"),
        storage_key=_string_field(reference, "storage_key"),
        hash_algorithm=_string_field(reference, "hash_algorithm"),
        content_hash=_string_field(reference, "content_hash"),
        size_bytes=_optional_int_field(reference, "size_bytes"),
    )


def _mentions_dataset(raw: str, dataset_id: str) -> bool:
    """Check whether a stored metadata document names this dataset exactly."""

    def walk(value: object) -> bool:
        if isinstance(value, str):
            return value == dataset_id
        if isinstance(value, dict):
            return any(walk(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(walk(item) for item in value)
        return False

    try:
        return walk(json.loads(raw))
    except (TypeError, ValueError):
        return False


def _as_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in value
    ):
        raise ValueError("metadata value must be an object with string keys")
    return {key: item for key, item in value.items()}


def _as_array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("metadata value must be an array")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("metadata value must be a string")
    return value


def _string_field(value: Mapping[str, object], key: str) -> str:
    return _string(value[key])


def _optional_string_field(value: Mapping[str, object], key: str) -> str | None:
    raw_value = value[key]
    return None if raw_value is None else _string(raw_value)


def _optional_int_field(value: Mapping[str, object], key: str) -> int | None:
    raw_value = value[key]
    if raw_value is not None and type(raw_value) is not int:
        raise ValueError(f"{key} metadata must be an integer or None")
    return raw_value


def _boolean_field(value: Mapping[str, object], key: str) -> bool:
    raw_value = value[key]
    if type(raw_value) is not bool:
        raise ValueError(f"{key} metadata must be a boolean")
    return raw_value


def _string_array(value: object) -> tuple[str, ...]:
    return tuple(_string(item) for item in _as_array(value))


def _string_pairs(value: object) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for raw_pair in _as_array(value):
        pair = _as_array(raw_pair)
        if len(pair) != 2:
            raise ValueError("metadata pair must contain two values")
        pairs.append((_string(pair[0]), _string(pair[1])))
    return tuple(pairs)


def _parameter_pairs(
    value: object,
) -> tuple[tuple[str, str | int | float | bool | None], ...]:
    pairs: list[tuple[str, str | int | float | bool | None]] = []
    for raw_pair in _as_array(value):
        pair = _as_array(raw_pair)
        if len(pair) != 2:
            raise ValueError("parameter pair must contain two values")
        key, parameter = _string(pair[0]), pair[1]
        if parameter is None:
            scalar = None
        elif isinstance(parameter, str):
            scalar = parameter
        elif isinstance(parameter, bool):
            scalar = parameter
        elif isinstance(parameter, int):
            scalar = parameter
        elif isinstance(parameter, float):
            scalar = parameter
        else:
            raise ValueError("parameter value must be an immutable scalar")
        pairs.append((key, scalar))
    return tuple(pairs)


def _encode_source(source: DataSource) -> str:
    return _pack(
        "DataSource",
        {
            "source_id": source.source_id,
            "name": source.name,
            "source_type": source.source_type,
            "description": source.description,
        },
    )


def _decode_source(raw: str) -> DataSource:
    try:
        value = _unpack(raw, "DataSource")
        return DataSource(
            source_id=_string_field(value, "source_id"),
            name=_string_field(value, "name"),
            source_type=_string_field(value, "source_type"),
            description=_optional_string_field(value, "description"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDefinitionError("Stored DataSource metadata cannot be restored.") from exc


def _encode_schema(schema: DatasetSchema) -> str:
    return _pack(
        "DatasetSchema",
        {
            "schema_id": schema.schema_id,
            "version": schema.version,
            "format_id": schema.format_id,
            "fields": [
                {
                    "name": field.name,
                    "data_type": field.data_type,
                    "required": field.required,
                    "nullable": field.nullable,
                    "temporal_role": (
                        field.temporal_role.value
                        if field.temporal_role is not None
                        else None
                    ),
                }
                for field in schema.fields
            ],
        },
    )


def _decode_schema(raw: str) -> DatasetSchema:
    try:
        value = _unpack(raw, "DatasetSchema")
        fields = []
        for raw_field in _as_array(value["fields"]):
            field = _as_object(raw_field)
            temporal_role = _optional_string_field(field, "temporal_role")
            fields.append(
                SchemaField(
                    name=_string_field(field, "name"),
                    data_type=_string_field(field, "data_type"),
                    required=_boolean_field(field, "required"),
                    nullable=_boolean_field(field, "nullable"),
                    temporal_role=(
                        TemporalFieldRole(temporal_role)
                        if temporal_role is not None
                        else None
                    ),
                )
            )
        return DatasetSchema(
            schema_id=_string_field(value, "schema_id"),
            version=_string_field(value, "version"),
            format_id=_optional_string_field(value, "format_id"),
            fields=tuple(fields),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDefinitionError("Stored DatasetSchema cannot be restored.") from exc


def _encode_lineage(lineage: ProcessingLineage) -> str:
    return _pack(
        "ProcessingLineage",
        {
            "lineage_id": lineage.lineage_id,
            "operation_name": lineage.operation_name,
            "operation_version": lineage.operation_version,
            "input_versions": [
                {"dataset_id": ref.dataset_id, "version_id": ref.version_id}
                for ref in lineage.input_versions
            ],
            "output_versions": [
                {"dataset_id": ref.dataset_id, "version_id": ref.version_id}
                for ref in lineage.output_versions
            ],
            "executed_at": lineage.executed_at.isoformat(),
            "parameters": [
                [key, value] for key, value in lineage.parameters
            ],
        },
    )


def _decode_lineage(raw: str) -> ProcessingLineage:
    try:
        value = _unpack(raw, "ProcessingLineage")
        inputs = tuple(
            _as_object(item) for item in _as_array(value["input_versions"])
        )
        outputs = tuple(
            _as_object(item) for item in _as_array(value["output_versions"])
        )
        return ProcessingLineage(
            lineage_id=_string_field(value, "lineage_id"),
            operation_name=_string_field(value, "operation_name"),
            operation_version=_string_field(value, "operation_version"),
            input_versions=tuple(
                DatasetVersionReference(
                    _string_field(item, "dataset_id"),
                    _string_field(item, "version_id"),
                )
                for item in inputs
            ),
            output_versions=tuple(
                DatasetVersionReference(
                    _string_field(item, "dataset_id"),
                    _string_field(item, "version_id"),
                )
                for item in outputs
            ),
            executed_at=datetime.fromisoformat(
                _string_field(value, "executed_at")
            ),
            parameters=_parameter_pairs(value["parameters"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDefinitionError("Stored ProcessingLineage cannot be restored.") from exc


def _encode_quality_report(report: QualityReport) -> str:
    return _pack(
        "QualityReport",
        {
            "report_id": report.report_id,
            "dataset_version": {
                "dataset_id": report.dataset_version.dataset_id,
                "version_id": report.dataset_version.version_id,
            },
            "rule_set_id": report.rule_set_id,
            "rule_set_version": report.rule_set_version,
            "checked_at": report.checked_at.isoformat(),
            "status": report.status.value,
            "findings": list(report.findings),
        },
    )


def _decode_quality_report(raw: str) -> QualityReport:
    try:
        value = _unpack(raw, "QualityReport")
        reference = _as_object(value["dataset_version"])
        return QualityReport(
            report_id=_string_field(value, "report_id"),
            dataset_version=DatasetVersionReference(
                _string_field(reference, "dataset_id"),
                _string_field(reference, "version_id"),
            ),
            rule_set_id=_string_field(value, "rule_set_id"),
            rule_set_version=_string_field(value, "rule_set_version"),
            checked_at=datetime.fromisoformat(
                _string_field(value, "checked_at")
            ),
            status=QualityStatus(_string_field(value, "status")),
            findings=_string_array(value["findings"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDefinitionError("Stored QualityReport cannot be restored.") from exc


def _encode_acquisition(record: AcquisitionRecord) -> str:
    return _pack(
        "AcquisitionRecord",
        {
            "acquisition_id": record.acquisition_id,
            "source_id": record.source_id,
            "dataset_version": {
                "dataset_id": record.dataset_version.dataset_id,
                "version_id": record.dataset_version.version_id,
            },
            "mode": record.mode.value,
            "acquired_at": record.acquired_at.isoformat(),
            "cursor_start": record.cursor_start,
            "cursor_end": record.cursor_end,
            "boundary": record.boundary,
            "metadata": [list(pair) for pair in record.metadata],
        },
    )


def _decode_acquisition(raw: str) -> AcquisitionRecord:
    try:
        value = _unpack(raw, "AcquisitionRecord")
        reference = _as_object(value["dataset_version"])
        return AcquisitionRecord(
            acquisition_id=_string_field(value, "acquisition_id"),
            source_id=_string_field(value, "source_id"),
            dataset_version=DatasetVersionReference(
                _string_field(reference, "dataset_id"),
                _string_field(reference, "version_id"),
            ),
            mode=AcquisitionMode(_string_field(value, "mode")),
            acquired_at=datetime.fromisoformat(
                _string_field(value, "acquired_at")
            ),
            cursor_start=_optional_string_field(value, "cursor_start"),
            cursor_end=_optional_string_field(value, "cursor_end"),
            boundary=_optional_string_field(value, "boundary"),
            metadata=_string_pairs(value["metadata"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDefinitionError("Stored AcquisitionRecord cannot be restored.") from exc


def _encode_dataset(dataset: Dataset) -> str:
    return _pack(
        "Dataset",
        {
            "dataset_id": dataset.dataset_id,
            "name": dataset.name,
            "source_ids": list(dataset.source_ids),
            "uniqueness_rule": (
                list(dataset.uniqueness_rule)
                if dataset.uniqueness_rule is not None
                else None
            ),
            "temporal_fields": [
                {"role": field.role.value, "field_name": field.field_name}
                for field in dataset.temporal_fields
            ],
            "description": dataset.description,
            "data_type": dataset.data_type,
            "market": dataset.market,
            "time_granularity": dataset.time_granularity,
            "format_id": dataset.format_id,
        },
    )


def _decode_dataset(raw: str) -> Dataset:
    try:
        value = _unpack(raw, "Dataset")
        temporal_fields = []
        for raw_field in _as_array(value["temporal_fields"]):
            field = _as_object(raw_field)
            temporal_fields.append(
                TemporalField(
                    TemporalFieldRole(_string_field(field, "role")),
                    _string_field(field, "field_name"),
                )
            )
        uniqueness = value["uniqueness_rule"]
        return Dataset(
            dataset_id=_string_field(value, "dataset_id"),
            name=_string_field(value, "name"),
            source_ids=_string_array(value["source_ids"]),
            uniqueness_rule=(
                None if uniqueness is None else _string_array(uniqueness)
            ),
            temporal_fields=tuple(temporal_fields),
            description=_optional_string_field(value, "description"),
            data_type=_optional_string_field(value, "data_type"),
            market=_optional_string_field(value, "market"),
            time_granularity=_optional_string_field(value, "time_granularity"),
            format_id=_optional_string_field(value, "format_id"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDefinitionError("Stored Dataset metadata cannot be restored.") from exc


def _encode_version(version: DatasetVersion) -> str:
    return _pack(
        "DatasetVersion",
        {
            "dataset_id": version.dataset_id,
            "version_id": version.version_id,
            "created_at": version.created_at.isoformat(),
            "data_layer": version.data_layer.value,
            "partitions": [
                {
                    "partition_id": partition.partition_id,
                    "partition_values": [list(pair) for pair in partition.partition_values],
                    "event_time_start": _datetime_value(partition.event_time_start),
                    "event_time_end": _datetime_value(partition.event_time_end),
                    "record_count": partition.record_count,
                    "content_reference": _content_reference_value(
                        partition.content_reference
                    ),
                }
                for partition in version.partitions
            ],
            "event_time_start": _datetime_value(version.event_time_start),
            "event_time_end": _datetime_value(version.event_time_end),
            "schema_id": version.schema_id,
            "schema_version": version.schema_version,
            "supersedes": _reference_value(version.supersedes),
        },
    )


def _decode_version(raw: str) -> DatasetVersion:
    try:
        value = _unpack(raw, "DatasetVersion")
        partitions_list = []
        for raw_partition in _as_array(value["partitions"]):
            partition = _as_object(raw_partition)
            partitions_list.append(
                DataPartition(
                    partition_id=_string_field(partition, "partition_id"),
                    partition_values=_string_pairs(partition["partition_values"]),
                    event_time_start=_parse_datetime(
                        partition["event_time_start"]
                    ),
                    event_time_end=_parse_datetime(partition["event_time_end"]),
                    record_count=_optional_int_field(partition, "record_count"),
                    content_reference=_parse_content_reference(
                        partition["content_reference"]
                    ),
                )
            )
        partitions = tuple(partitions_list)
        return DatasetVersion(
            dataset_id=_string_field(value, "dataset_id"),
            version_id=_string_field(value, "version_id"),
            created_at=datetime.fromisoformat(
                _string_field(value, "created_at")
            ),
            data_layer=DataLayer(_string_field(value, "data_layer")),
            partitions=partitions,
            event_time_start=_parse_datetime(value["event_time_start"]),
            event_time_end=_parse_datetime(value["event_time_end"]),
            schema_id=_optional_string_field(value, "schema_id"),
            schema_version=_optional_string_field(value, "schema_version"),
            supersedes=_parse_reference(value["supersedes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDefinitionError(
            "Stored DatasetVersion metadata cannot be restored."
        ) from exc


def _encode_snapshot(snapshot: DatasetSnapshot) -> str:
    return _pack(
        "DatasetSnapshot",
        {
            "snapshot_id": snapshot.snapshot_id,
            "members": [
                {"dataset_id": ref.dataset_id, "version_id": ref.version_id}
                for ref in snapshot.members
            ],
            "partition_sources": [
                {
                    "dataset_id": source.dataset_id,
                    "partition_values": [
                        list(pair) for pair in source.partition_values
                    ],
                    "source_version": {
                        "dataset_id": source.source_version.dataset_id,
                        "version_id": source.source_version.version_id,
                    },
                    "partition_id": source.partition_id,
                }
                for source in snapshot.partition_sources
            ],
        },
    )


def _decode_snapshot(raw: str) -> DatasetSnapshot:
    try:
        value = _unpack(raw, "DatasetSnapshot")
        members_list = []
        for raw_member in _as_array(value["members"]):
            member = _as_object(raw_member)
            members_list.append(
                DatasetVersionReference(
                    _string_field(member, "dataset_id"),
                    _string_field(member, "version_id"),
                )
            )
        sources_list = []
        for raw_source in _as_array(value["partition_sources"]):
            source = _as_object(raw_source)
            version_reference = _as_object(source["source_version"])
            sources_list.append(
                SnapshotPartitionSource(
                    dataset_id=_string_field(source, "dataset_id"),
                    partition_values=_string_pairs(source["partition_values"]),
                    source_version=DatasetVersionReference(
                        _string_field(version_reference, "dataset_id"),
                        _string_field(version_reference, "version_id"),
                    ),
                    partition_id=_string_field(source, "partition_id"),
                )
            )
        return DatasetSnapshot(
            snapshot_id=_string_field(value, "snapshot_id"),
            members=tuple(members_list),
            partition_sources=tuple(sources_list),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDefinitionError(
            "Stored DatasetSnapshot metadata cannot be restored."
        ) from exc


class SQLiteDatasetRepository:
    """DatasetRepository adapter for a shared SQLite metadata store."""

    def __init__(self, store: _SQLiteMetadataStore) -> None:
        self._store = store

    def get(self, dataset_id: str) -> Dataset | None:
        return self._store.get_dataset(dataset_id)

    def list_all(self) -> tuple[Dataset, ...]:
        return self._store.list_datasets()

    def register(self, dataset: Dataset) -> None:
        self._store.register(dataset)

    def update(self, dataset: Dataset) -> None:
        self._store.update_dataset(dataset)

    def archive(self, dataset_id: str) -> None:
        self._store.archive_dataset(dataset_id)

    def restore(self, dataset_id: str) -> None:
        self._store.restore_dataset(dataset_id)

    def archived_ids(self) -> tuple[str, ...]:
        return self._store.archived_dataset_ids()


class SQLiteDatasetVersionRepository:
    """DatasetVersionRepository adapter for a shared SQLite metadata store."""

    def __init__(self, store: _SQLiteMetadataStore) -> None:
        self._store = store

    def get(self, reference: DatasetVersionReference) -> DatasetVersion | None:
        return self._store.get_version(reference)

    def list_for_dataset(self, dataset_id: str) -> tuple[DatasetVersion, ...]:
        return self._store.list_versions(dataset_id)

    def get_head(self, dataset_id: str) -> DatasetVersionReference | None:
        return self._store.get_head(dataset_id)

    def save_candidate(self, version: DatasetVersion) -> None:
        self._store.save_candidate(version)

    def publish_candidate(
        self,
        reference: DatasetVersionReference,
        expected_head: DatasetVersionReference | None,
    ) -> bool:
        return self._store.publish_candidate(reference, expected_head)

    def retract_version(
        self,
        reference: DatasetVersionReference,
        *,
        restore_head: DatasetVersionReference | None,
    ) -> bool:
        return self._store.retract_version(
            reference,
            restore_head=restore_head,
        )


class SQLiteSnapshotRepository:
    """SnapshotRepository adapter for a shared SQLite metadata store."""

    def __init__(self, store: _SQLiteMetadataStore) -> None:
        self._store = store

    def get(self, snapshot_id: str) -> DatasetSnapshot | None:
        return self._store.get_snapshot(snapshot_id)

    def list_all(self) -> tuple[DatasetSnapshot, ...]:
        return self._store.list_snapshots()

    def save(self, snapshot: DatasetSnapshot) -> None:
        self._store.save_snapshot(snapshot)


class SQLiteDataSourceRepository:
    """DataSourceRepository adapter for a shared SQLite metadata store."""

    def __init__(self, store: _SQLiteMetadataStore) -> None:
        self._store = store

    def get(self, source_id: str) -> DataSource | None:
        return self._store.get_source(source_id)

    def list_all(self) -> tuple[DataSource, ...]:
        return self._store.list_sources()

    def register(self, source: DataSource) -> None:
        self._store.register_source(source)


class SQLiteDatasetSchemaRepository:
    """DatasetSchemaRepository adapter for a shared SQLite metadata store."""

    def __init__(self, store: _SQLiteMetadataStore) -> None:
        self._store = store

    def get(self, schema_id: str, version: str) -> DatasetSchema | None:
        return self._store.get_schema(schema_id, version)

    def register(self, schema: DatasetSchema) -> None:
        self._store.register_schema(schema)


class SQLiteProcessingLineageRepository:
    """ProcessingLineageRepository adapter for a shared SQLite metadata store."""

    def __init__(self, store: _SQLiteMetadataStore) -> None:
        self._store = store

    def get(self, lineage_id: str) -> ProcessingLineage | None:
        return self._store.get_lineage(lineage_id)

    def list_all(self) -> tuple[ProcessingLineage, ...]:
        return self._store.list_lineages()

    def save(self, lineage: ProcessingLineage) -> None:
        self._store.save_lineage(lineage)


class SQLiteQualityReportRepository:
    """QualityReportRepository adapter for a shared SQLite metadata store."""

    def __init__(self, store: _SQLiteMetadataStore) -> None:
        self._store = store

    def get(self, report_id: str) -> QualityReport | None:
        return self._store.get_quality_report(report_id)

    def list_all(self) -> tuple[QualityReport, ...]:
        return self._store.list_quality_reports()

    def save(self, report: QualityReport) -> None:
        self._store.save_quality_report(report)


class SQLiteAcquisitionRepository:
    """AcquisitionRepository adapter for a shared SQLite metadata store."""

    def __init__(self, store: _SQLiteMetadataStore) -> None:
        self._store = store

    def get(self, acquisition_id: str) -> AcquisitionRecord | None:
        return self._store.get_acquisition(acquisition_id)

    def save(self, record: AcquisitionRecord) -> None:
        self._store.save_acquisition(record)


class SQLiteMetadataRepository:
    """Bundle SQLite adapters for the three metadata Protocols."""

    def __init__(self, database_path: str | Path) -> None:
        store = _SQLiteMetadataStore(database_path)
        self._store = store
        self.datasets = SQLiteDatasetRepository(store)
        self.versions = SQLiteDatasetVersionRepository(store)
        self.snapshots = SQLiteSnapshotRepository(store)
        self.sources = SQLiteDataSourceRepository(store)
        self.schemas = SQLiteDatasetSchemaRepository(store)
        self.lineages = SQLiteProcessingLineageRepository(store)
        self.quality_reports = SQLiteQualityReportRepository(store)
        self.acquisitions = SQLiteAcquisitionRepository(store)

    def purge_dataset(
        self, dataset_id: str
    ) -> tuple[tuple[ContentReference, ...], int, int]:
        """Forward an irreversible deletion to the shared metadata store."""
        return self._store.purge_dataset(dataset_id)
