"""Stable read-only entry point for external Data module consumers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

from dynaloop.data.domain.errors import (
    DataDefinitionError,
    DataNotFoundError,
    QualityGateError,
)
from dynaloop.data.domain.models import (
    AcquisitionMode,
    AcquisitionRecord,
    Dataset,
    DatasetSchema,
    DataSource,
    DatasetSnapshot,
    DatasetVersion,
    DatasetVersionReference,
    FetchRequest,
    ProcessingLineage,
    QualityReport,
    QualityStatus,
    SnapshotPartitionSource,
)
from dynaloop.data.interfaces.protocols import (
    AcquisitionRepository,
    DataReader,
    FormatAdapter,
    SourceAdapter,
    DataSourceRepository,
    DatasetMaintenance,
    DatasetPurgeResult,
    DatasetSchemaRepository,
    DatasetRepository,
    DatasetVersionRepository,
    ProcessingLineageRepository,
    QualityReportRepository,
    SnapshotRepository,
)
from dynaloop.data.services.acquisition import (
    AcquisitionService,
    CsvFormatAdapter,
)
from dynaloop.data.services.adapter_registry import AdapterRegistry
from dynaloop.data.services.default_adapters import build_default_registries
from dynaloop.data.services.distribution import (
    ColumnDistribution,
    summarize_column_distribution,
)
from dynaloop.data.services.processing import (
    ProcessingOutput,
    ProcessingService,
    Record,
    RecordSet,
)
from dynaloop.data.services.publishing import DatasetVersionPublishingService
from dynaloop.data.services.quality import QualityChecker, QualityService

RecordT = TypeVar("RecordT")


class DataFacade(Generic[RecordT]):
    """Expose dataset lookup and logical partition reads without storage details."""

    def __init__(
        self,
        datasets: DatasetRepository,
        versions: DatasetVersionRepository,
        reader: DataReader[RecordT],
        *,
        publisher: DatasetVersionPublishingService | None = None,
        snapshots: SnapshotRepository | None = None,
        sources: DataSourceRepository | None = None,
        schemas: DatasetSchemaRepository | None = None,
        acquisitions: AcquisitionRepository | None = None,
        lineages: ProcessingLineageRepository | None = None,
        quality_reports: QualityReportRepository | None = None,
        acquisition_service: AcquisitionService | None = None,
        processing_service: ProcessingService | None = None,
        quality_service: QualityService | None = None,
        maintenance: DatasetMaintenance | None = None,
    ) -> None:
        self._datasets = datasets
        self._versions = versions
        self._reader = reader
        self._publisher = publisher
        self._snapshots = snapshots
        self._sources = sources
        self._schemas = schemas
        self._acquisitions = acquisitions
        self._lineages = lineages
        self._quality_reports = quality_reports
        self._acquisition_service = acquisition_service
        self._processing_service = processing_service
        self._quality_service = quality_service
        self._maintenance = maintenance

    @classmethod
    def open_local(
        cls,
        database_path: str | Path,
        storage_root: str | Path,
    ) -> DataFacade[bytes]:
        """Open a local persistent Data facade using SQLite and filesystem storage."""
        from dynaloop.data.infrastructure.filesystem_storage import (
            LocalFileStorageBackend,
        )
        from dynaloop.data.infrastructure.local_reader import LocalDataReader
        from dynaloop.data.infrastructure.purge import SQLiteDatasetMaintenance
        from dynaloop.data.infrastructure.sqlite_repository import (
            SQLiteMetadataRepository,
        )
        from dynaloop.data.services.acquisition import AcquisitionService
        from dynaloop.data.services.processing import ProcessingService
        from dynaloop.data.services.quality import QualityService

        metadata = SQLiteMetadataRepository(database_path)
        storage = LocalFileStorageBackend(storage_root)
        publisher = DatasetVersionPublishingService(
            metadata.datasets,
            metadata.versions,
            storage,
        )
        reader = LocalDataReader(metadata.versions, storage)
        return DataFacade[bytes](
            metadata.datasets,
            metadata.versions,
            reader,
            publisher=publisher,
            snapshots=metadata.snapshots,
            sources=metadata.sources,
            schemas=metadata.schemas,
            acquisitions=metadata.acquisitions,
            lineages=metadata.lineages,
            quality_reports=metadata.quality_reports,
            acquisition_service=AcquisitionService(
                metadata.sources,
                metadata.acquisitions,
                publisher,
            ),
            processing_service=ProcessingService(
                metadata.versions,
                reader,
                metadata.schemas,
                publisher,
                metadata.lineages,
            ),
            quality_service=QualityService(
                metadata.versions,
                metadata.schemas,
                reader,
                storage,
                metadata.quality_reports,
            ),
            maintenance=SQLiteDatasetMaintenance(metadata, storage),
        )

    def register_dataset(self, dataset: Dataset) -> None:
        """Register a dataset through a configured writable repository."""
        if not isinstance(dataset, Dataset):
            raise DataDefinitionError("dataset must be a Dataset.")
        self._datasets.register(dataset)

    def list_datasets(self) -> tuple[Dataset, ...]:
        """List registered datasets without exposing their repository."""
        return self._datasets.list_all()

    def hidden_dataset_ids(self) -> tuple[str, ...]:
        """Identifiers hidden from management views; stored bytes are untouched."""
        return self._datasets.archived_ids()

    def visible_datasets(self) -> tuple[Dataset, ...]:
        """Registered datasets that are not archived.

        Archiving is a management-plane flag only. Every consumer that decides
        whether a dataset ID is available must go through this view instead of
        filtering in one HTTP handler.
        """
        hidden = set(self.hidden_dataset_ids())
        return tuple(
            item for item in self.list_datasets() if item.dataset_id not in hidden
        )

    def replace_dataset_definition(self, dataset: Dataset) -> None:
        """Replace a descriptive definition when an archived ID is reused."""
        if not isinstance(dataset, Dataset):
            raise DataDefinitionError("dataset must be a Dataset.")
        self._datasets.update(dataset)

    def update_dataset_metadata(
        self,
        dataset_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Dataset:
        """Edit descriptive fields only; dataset identity stays immutable."""
        existing = self._datasets.get(dataset_id)
        if existing is None:
            raise DataNotFoundError(f"Dataset '{dataset_id}' was not found.")
        changes: dict[str, str | None] = {}
        if name is not None:
            if not name.strip():
                raise DataDefinitionError("Dataset name must be non-empty.")
            changes["name"] = name.strip()
        if description is not None:
            changes["description"] = description
        updated = replace(existing, **changes)
        self._datasets.update(updated)
        return updated

    def hide_dataset(self, dataset_id: str) -> None:
        """Soft-delete a dataset; versions and content remain recoverable."""
        if self._datasets.get(dataset_id) is None:
            raise DataNotFoundError(f"Dataset '{dataset_id}' was not found.")
        self._datasets.archive(dataset_id)

    def restore_dataset(self, dataset_id: str) -> None:
        """Undo a soft delete; a purged dataset no longer exists to restore."""
        self.get_dataset(dataset_id)
        self._datasets.restore(dataset_id)

    def purge_dataset(self, dataset_id: str) -> DatasetPurgeResult:
        """Permanently delete an archived dataset, its versions and its bytes.

        Requires a management backend; read-only facades cannot destroy data.
        """
        if self._maintenance is None:
            raise DataDefinitionError(
                "Permanent dataset deletion is not configured for this facade."
            )
        return self._maintenance.purge(dataset_id)

    def register_data_source(self, source: DataSource) -> None:
        """Register descriptive source metadata without credential storage."""
        if self._sources is None:
            raise DataDefinitionError("Data source registration is not configured.")
        self._sources.register(source)

    def list_data_sources(self) -> tuple[DataSource, ...]:
        """List registered source descriptions."""
        if self._sources is None:
            raise DataDefinitionError("Data source listing is not configured.")
        return self._sources.list_all()

    def register_schema(self, schema: DatasetSchema) -> None:
        """Register a dataset-specific immutable schema version."""
        if self._schemas is None:
            raise DataDefinitionError("Schema registration is not configured.")
        self._schemas.register(schema)

    def get_schema(self, schema_id: str, version: str) -> DatasetSchema:
        """Return a registered schema version."""
        if self._schemas is None:
            raise DataDefinitionError("Schema access is not configured.")
        schema = self._schemas.get(schema_id, version)
        if schema is None:
            raise DataNotFoundError(f"Schema '{schema_id}@{version}' was not found.")
        return schema

    def publish_version(
        self,
        dataset: Dataset,
        version: DatasetVersion,
        expected_head: DatasetVersionReference | None,
        partition_contents: Mapping[str, Iterable[bytes]],
    ) -> DatasetVersionReference:
        """Publish through the configured service without exposing adapter details."""
        if self._publisher is None:
            raise DataDefinitionError("Dataset version publishing is not configured.")
        return self._publisher.publish_version(
            dataset,
            version,
            expected_head,
            partition_contents,
        )

    def get_snapshot(self, snapshot_id: str) -> DatasetSnapshot:
        """Return a persisted Snapshot or raise DataNotFoundError."""
        self._validate_text_id(snapshot_id, "snapshot_id")
        if self._snapshots is None:
            raise DataDefinitionError("Snapshot persistence is not configured.")
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise DataNotFoundError(f"Dataset snapshot '{snapshot_id}' was not found.")
        return snapshot

    def list_snapshots(self) -> tuple[DatasetSnapshot, ...]:
        """List saved Snapshot manifests."""
        if self._snapshots is None:
            raise DataDefinitionError("Snapshot listing is not configured.")
        return self._snapshots.list_all()

    def save_snapshot(self, snapshot: DatasetSnapshot) -> None:
        """Persist a Snapshot through the configured repository."""
        if not isinstance(snapshot, DatasetSnapshot):
            raise DataDefinitionError("snapshot must be a DatasetSnapshot.")
        if self._snapshots is None:
            raise DataDefinitionError("Snapshot persistence is not configured.")
        self._snapshots.save(snapshot)

    def import_files(
        self,
        source_id: str,
        dataset: Dataset,
        version: DatasetVersion,
        expected_head: DatasetVersionReference | None,
        files: Mapping[str, str | Path],
        *,
        mode: AcquisitionMode = AcquisitionMode.BATCH,
        cursor: str | None = None,
        csv_adapter: CsvFormatAdapter | None = None,
        acquisition_id: str | None = None,
        quality_policy: str,
    ) -> DatasetVersionReference:
        """Acquire local files through the configured format and publication services.

        ``quality_policy`` is explicit and has no default: ``"report_only"``
        publishes without an automatic quality check; ``"gate_on_fail"`` runs
        the configured QualityService after publication and, on FAILED,
        retracts the version (restoring the previous Head) and raises
        QualityGateError, leaving the failing quality report persisted.
        """
        self._validate_quality_policy(quality_policy)
        if self._acquisition_service is None:
            raise DataDefinitionError("Data acquisition is not configured.")
        reference = self._acquisition_service.import_files(
            source_id,
            dataset,
            version,
            expected_head,
            files,
            mode=mode,
            cursor=cursor,
            csv_adapter=csv_adapter,
            acquisition_id=acquisition_id,
        )
        self._apply_quality_gate(dataset, reference, expected_head, quality_policy)
        return reference

    def import_source(
        self,
        source_id: str,
        dataset: Dataset,
        version: DatasetVersion,
        expected_head: DatasetVersionReference | None,
        requests: Mapping[str, FetchRequest],
        *,
        format_id: str | None = None,
        format_adapter: FormatAdapter | None = None,
        source_adapter: SourceAdapter | None = None,
        acquisition_id: str | None = None,
        quality_policy: str,
    ) -> DatasetVersionReference:
        """Acquire bytes from any registered source through the same publishing path."""
        self._validate_quality_policy(quality_policy)
        if self._acquisition_service is None:
            raise DataDefinitionError("Data acquisition is not configured.")
        reference = self._acquisition_service.import_source(
            source_id,
            dataset,
            version,
            expected_head,
            requests,
            format_id=format_id,
            format_adapter=format_adapter,
            source_adapter=source_adapter,
            acquisition_id=acquisition_id,
        )
        self._apply_quality_gate(dataset, reference, expected_head, quality_policy)
        return reference

    def configure_adapters(
        self,
        source_adapters: AdapterRegistry[Any],
        format_adapters: AdapterRegistry[Any],
    ) -> None:
        """Bind external registries so catalog views and imports agree."""
        if self._acquisition_service is None:
            raise DataDefinitionError("Data acquisition is not configured.")
        self._acquisition_service.use_registries(source_adapters, format_adapters)

    def adapter_registries(self) -> tuple[AdapterRegistry[Any], AdapterRegistry[Any]]:
        """Return the registries actually used by the acquisition service."""
        if self._acquisition_service is None:
            return build_default_registries()
        return (
            self._acquisition_service.source_registry,
            self._acquisition_service.format_registry,
        )

    @staticmethod
    def _validate_quality_policy(quality_policy: str) -> None:
        if quality_policy not in ("report_only", "gate_on_fail"):
            raise DataDefinitionError(
                "quality_policy must be 'report_only' or 'gate_on_fail'."
            )

    def _apply_quality_gate(
        self,
        dataset: Dataset,
        reference: DatasetVersionReference,
        expected_head: DatasetVersionReference | None,
        quality_policy: str,
    ) -> None:
        if quality_policy != "gate_on_fail":
            return
        if self._quality_service is None:
            raise DataDefinitionError("Quality checking is not configured.")
        report = self._quality_service.check_version(dataset, reference)
        if report.status is QualityStatus.FAILED:
            retracted = self._versions.retract_version(
                reference,
                restore_head=expected_head,
            )
            detail = (
                f"Quality gate FAILED for version {reference.version_id!r} "
                f"under rule set {report.rule_set_id!r} v{report.rule_set_version!r}; "
                f"findings: {len(report.findings)}."
            )
            if not retracted:
                raise QualityGateError(
                    f"{detail} The version could not be retracted automatically."
                )
            raise QualityGateError(f"{detail} The version was retracted.")

    def process(
        self,
        *,
        lineage_id: str,
        operation_name: str,
        operation_version: str,
        input_versions: tuple[DatasetVersionReference, ...],
        outputs: tuple[ProcessingOutput, ...],
        transform: Callable[
            [Mapping[DatasetVersionReference, RecordSet]],
            Mapping[str, Mapping[str, Iterable[Record]]],
        ],
        parameters: tuple[
            tuple[str, str | int | float | bool | None],
            ...,
        ] = (),
    ) -> ProcessingLineage:
        """Run an injected processor and publish its outputs with stored lineage."""
        if self._processing_service is None:
            raise DataDefinitionError("Data processing is not configured.")
        return self._processing_service.process(
            lineage_id=lineage_id,
            operation_name=operation_name,
            operation_version=operation_version,
            input_versions=input_versions,
            outputs=outputs,
            transform=transform,
            parameters=parameters,
        )

    def check_quality(
        self,
        dataset: Dataset,
        reference: DatasetVersionReference,
        *,
        checker: QualityChecker | None = None,
    ) -> QualityReport:
        """Run schema/integrity checks or an injected checker and persist a report."""
        if self._quality_service is None:
            raise DataDefinitionError("Quality checking is not configured.")
        if checker is not None:
            # A caller-selected checker is scoped to this call; it does not mutate the facade.
            service = self._quality_service.with_checker(checker)
            return service.check_version(dataset, reference)
        return self._quality_service.check_version(dataset, reference)

    def get_acquisition(self, acquisition_id: str) -> AcquisitionRecord:
        self._validate_text_id(acquisition_id, "acquisition_id")
        if self._acquisitions is None:
            raise DataDefinitionError("Acquisition metadata is not configured.")
        record = self._acquisitions.get(acquisition_id)
        if record is None:
            raise DataNotFoundError(f"Acquisition '{acquisition_id}' was not found.")
        return record

    def get_lineage(self, lineage_id: str) -> ProcessingLineage:
        self._validate_text_id(lineage_id, "lineage_id")
        if self._lineages is None:
            raise DataDefinitionError("Processing lineage is not configured.")
        lineage = self._lineages.get(lineage_id)
        if lineage is None:
            raise DataNotFoundError(f"Processing lineage '{lineage_id}' was not found.")
        return lineage

    def list_lineages(self) -> tuple[ProcessingLineage, ...]:
        """List processing lineage records."""
        if self._lineages is None:
            raise DataDefinitionError("Processing lineage listing is not configured.")
        return self._lineages.list_all()

    def get_quality_report(self, report_id: str) -> QualityReport:
        self._validate_text_id(report_id, "report_id")
        if self._quality_reports is None:
            raise DataDefinitionError("Quality reports are not configured.")
        report = self._quality_reports.get(report_id)
        if report is None:
            raise DataNotFoundError(f"Quality report '{report_id}' was not found.")
        return report

    def list_quality_reports(self) -> tuple[QualityReport, ...]:
        """List persisted quality reports."""
        if self._quality_reports is None:
            raise DataDefinitionError("Quality report listing is not configured.")
        return self._quality_reports.list_all()

    @staticmethod
    def _validate_text_id(value: str, field_name: str) -> None:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
        ):
            raise DataDefinitionError(
                f"{field_name} must be a non-empty, trimmed string."
            )

    def get_dataset(self, dataset_id: str) -> Dataset:
        """Return a logical dataset or raise DataNotFoundError."""
        if (
            not isinstance(dataset_id, str)
            or not dataset_id.strip()
            or dataset_id != dataset_id.strip()
        ):
            raise DataDefinitionError("dataset_id must be a non-empty, trimmed string.")
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise DataNotFoundError(f"Dataset '{dataset_id}' was not found.")
        if not isinstance(dataset, Dataset) or dataset.dataset_id != dataset_id:
            raise DataDefinitionError(
                f"Dataset repository returned an invalid result for '{dataset_id}'."
            )
        return dataset

    def get_dataset_version(self, reference: DatasetVersionReference) -> DatasetVersion:
        """Return an immutable version or raise DataNotFoundError."""
        if not isinstance(reference, DatasetVersionReference):
            raise DataDefinitionError("reference must be a DatasetVersionReference.")
        version = self._versions.get(reference)
        if version is None:
            raise DataNotFoundError(
                f"Dataset version '{reference.dataset_id}@{reference.version_id}' was not found."
            )
        if not isinstance(version, DatasetVersion) or version.reference != reference:
            raise DataDefinitionError(
                "Dataset version repository returned a result that does not match the reference."
            )
        return version

    def list_dataset_versions(
        self,
        dataset_id: str,
    ) -> tuple[DatasetVersion, ...]:
        """List only published versions belonging to a dataset."""
        self.get_dataset(dataset_id)
        return self._versions.list_for_dataset(dataset_id)

    def get_dataset_head(
        self,
        dataset_id: str,
    ) -> DatasetVersionReference | None:
        """Return the published Head for a registered dataset, if one exists."""
        self.get_dataset(dataset_id)
        return self._versions.get_head(dataset_id)

    def read_partition(
        self,
        reference: DatasetVersionReference,
        partition_id: str,
    ) -> Iterable[RecordT]:
        """Read a logical partition through the injected reader boundary."""
        if (
            not isinstance(partition_id, str)
            or not partition_id.strip()
            or partition_id != partition_id.strip()
        ):
            raise DataDefinitionError("partition_id must be a non-empty, trimmed string.")
        self.get_dataset_version(reference)
        return self._reader.read_partition(reference, partition_id)

    def read_batch(
        self,
        requests: Iterable[tuple[DatasetVersionReference, str]],
    ) -> Mapping[tuple[DatasetVersionReference, str], bytes]:
        """Read an explicit batch of immutable version/partition references."""
        result: dict[tuple[DatasetVersionReference, str], bytes] = {}
        for reference, partition_id in requests:
            key = (reference, partition_id)
            if key in result:
                raise DataDefinitionError(f"Duplicate batch read request {key!r}.")
            result[key] = self._read_partition_bytes(reference, partition_id)
        return result

    def read_version(self, reference: DatasetVersionReference) -> Mapping[str, bytes]:
        """Read every partition from one fixed published version."""
        version = self.get_dataset_version(reference)
        return {
            partition.partition_id: self._read_partition_bytes(
                reference,
                partition.partition_id,
            )
            for partition in version.partitions
        }

    def read_snapshot(
        self,
        snapshot_id: str,
    ) -> Mapping[SnapshotPartitionSource, bytes]:
        """Read only the explicit source partitions declared by a Snapshot."""
        snapshot = self.get_snapshot(snapshot_id)
        return {
            source: self._read_partition_bytes(
                source.source_version,
                source.partition_id,
            )
            for source in snapshot.partition_sources
        }

    def read_incremental(
        self,
        reference: DatasetVersionReference,
        partition_id: str,
        cursor: str,
        *,
        max_bytes: int | None = None,
    ) -> tuple[bytes, str]:
        """Read raw bytes after an explicit byte-offset cursor in a fixed version."""
        if not isinstance(cursor, str) or not cursor.isdecimal():
            raise DataDefinitionError("cursor must be a non-negative byte-offset string.")
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
            raise DataDefinitionError("max_bytes must be a non-negative integer or None.")
        content = self._read_partition_bytes(reference, partition_id)
        offset = int(cursor)
        if offset > len(content):
            raise DataDefinitionError("cursor exceeds the partition content size.")
        end = len(content) if max_bytes is None else min(len(content), offset + max_bytes)
        return content[offset:end], str(end)

    def query_json_lines(
        self,
        reference: DatasetVersionReference,
        partition_id: str,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        """Filter JSON Lines records by exact field equality.

        This intentionally small query surface does not parse or reinterpret
        arbitrary binary content; callers choose the record format explicitly.
        """
        raw = self._read_partition_bytes(reference, partition_id)
        rows: list[Mapping[str, object]] = []
        line_number = 0
        try:
            for line_number, line in enumerate(raw.splitlines(), 1):
                if not line:
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("record must be a JSON object")
                if filters is None or all(record.get(key) == value for key, value in filters.items()):
                    rows.append(record)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise DataDefinitionError(
                f"Partition '{partition_id}' is not valid JSON Lines "
                f"(line {line_number})."
            ) from exc
        return tuple(rows)

    def get_column_distribution(
        self,
        reference: DatasetVersionReference,
        partition_id: str,
        column: str,
    ) -> ColumnDistribution:
        """Summarize one column over the complete published partition.

        Bucketing rules are fixed and reproducible (see services.distribution).
        """
        records = self.query_json_lines(reference, partition_id)
        return summarize_column_distribution(records, column)

    def _read_partition_bytes(
        self,
        reference: DatasetVersionReference,
        partition_id: str,
    ) -> bytes:
        content = bytearray()
        for chunk in self.read_partition(reference, partition_id):
            if not isinstance(chunk, bytes):
                raise DataDefinitionError(
                    "DataReader must return bytes for raw content access."
                )
            content.extend(chunk)
        return bytes(content)
