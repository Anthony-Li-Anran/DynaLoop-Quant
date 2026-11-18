"""Immutable domain values for dataset identity, versions, and quality."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite

from dynaloop.data.domain.errors import (
    DataDefinitionError,
    DatasetSnapshotError,
    DatasetVersionValidationError,
)


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DataDefinitionError(f"{field_name} must be a non-empty, trimmed string.")
    return value


def _require_aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise DataDefinitionError(f"{field_name} must be a timezone-aware datetime.")
    return value


def _freeze_text_pairs(
    values: object,
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(values, (tuple, list)):
        raise DataDefinitionError(f"{field_name} must be a tuple or list of string pairs.")
    pairs = tuple(values)
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise DataDefinitionError(f"Each {field_name} entry must be a pair of strings.")
        key, value = pair
        _require_text(key, f"{field_name} key")
        _require_text(value, f"{field_name} value")
    return tuple((pair[0], pair[1]) for pair in pairs)


def _freeze_texts(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise DataDefinitionError(f"{field_name} must be a tuple or list of strings.")
    return tuple(_require_text(value, field_name) for value in values)


def _freeze_parameters(
    values: object,
) -> tuple[tuple[str, str | int | float | bool | None], ...]:
    if not isinstance(values, (tuple, list)):
        raise DataDefinitionError("parameters must be a tuple or list of key/value pairs.")
    pairs = tuple(values)
    result: list[tuple[str, str | int | float | bool | None]] = []
    seen_keys: set[str] = set()
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise DataDefinitionError("Each parameters entry must be a key/value pair.")
        key, raw_value = pair
        _require_text(key, "parameter key")
        if key in seen_keys:
            raise DataDefinitionError(f"parameters contains duplicate key '{key}'.")
        seen_keys.add(key)
        if isinstance(raw_value, (tuple, list, dict, set, bytearray)):
            raise DataDefinitionError(
                "parameter values must be immutable scalar values."
            )
        if raw_value is not None and type(raw_value) not in (str, int, float, bool):
            raise DataDefinitionError(
                "parameter values must be strings, numbers, booleans, or None."
            )
        if isinstance(raw_value, float) and not isfinite(raw_value):
            raise DataDefinitionError("float parameter values must be finite.")
        result.append((key, raw_value))
    return tuple(result)


def _partition_key(partition_values: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(partition_values))


def _validate_time_range(
    start: datetime | None,
    end: datetime | None,
    field_name: str,
) -> None:
    if (start is None) != (end is None):
        raise DataDefinitionError(f"{field_name} bounds must be provided together.")
    if start is not None and end is not None:
        if end.astimezone(timezone.utc) <= start.astimezone(timezone.utc):
            raise DataDefinitionError(f"{field_name} end must be later than its start.")


class TemporalFieldRole(Enum):
    """Distinct temporal meanings that may be present in source data."""

    EVENT_TIME = "event_time"
    INGESTION_TIME = "ingestion_time"
    AVAILABILITY_TIME = "availability_time"
    PROCESSING_TIME = "processing_time"
    REPORT_PERIOD = "report_period"
    PUBLICATION_TIME = "publication_time"
    REVISION_TIME = "revision_time"


class DataLayer(Enum):
    """Whether a dataset version represents acquired or processed data."""

    RAW = "raw"
    PROCESSED = "processed"


class QualityStatus(Enum):
    """Outcome reported by a quality assessment; it does not gate publishing."""

    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


class AcquisitionMode(Enum):
    """Supported high-level ingestion modes; adapters advertise actual support."""

    BATCH = "batch"
    INCREMENTAL = "incremental"
    POLLING = "polling"
    STREAMING = "streaming"


@dataclass(frozen=True, slots=True)
class DatasetVersionReference:
    """Stable reference to one immutable version of a logical dataset."""

    dataset_id: str
    version_id: str

    def __post_init__(self) -> None:
        _require_text(self.dataset_id, "dataset_id")
        _require_text(self.version_id, "version_id")


@dataclass(frozen=True, slots=True)
class ContentReference:
    """Backend-neutral identity and integrity metadata for immutable content.

    ``storage_key`` is opaque to domain consumers and is interpreted only by
    the backend identified by ``backend_id``. The hash is hexadecimal; the
    backend is responsible for supporting and verifying the named algorithm.
    """

    backend_id: str
    storage_key: str
    hash_algorithm: str
    content_hash: str
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.backend_id, "backend_id")
        _require_text(self.storage_key, "storage_key")
        _require_text(self.hash_algorithm, "hash_algorithm")
        _require_text(self.content_hash, "content_hash")
        if any(character not in "0123456789abcdefABCDEF" for character in self.content_hash):
            raise DataDefinitionError("content_hash must be a non-empty hexadecimal digest.")
        if self.size_bytes is not None and (
            type(self.size_bytes) is not int or self.size_bytes < 0
        ):
            raise DataDefinitionError("size_bytes must be a non-negative integer or None.")


@dataclass(frozen=True, slots=True)
class TemporalField:
    """Names a data field and the temporal meaning assigned to it."""

    role: TemporalFieldRole
    field_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, TemporalFieldRole):
            raise DataDefinitionError("role must be a supported TemporalFieldRole.")
        _require_text(self.field_name, "field_name")


@dataclass(frozen=True, slots=True)
class DataSource:
    """Identity and human-readable description of an acquisition source."""

    source_id: str
    name: str
    source_type: str
    description: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.name, "name")
        _require_text(self.source_type, "source_type")
        if self.description is not None and not isinstance(self.description, str):
            raise DataDefinitionError("description must be a string or None.")


@dataclass(frozen=True, slots=True)
class Dataset:
    """Stable logical dataset identity and its declared data semantics."""

    dataset_id: str
    name: str
    source_ids: tuple[str, ...] = ()
    uniqueness_rule: tuple[str, ...] | None = None
    temporal_fields: tuple[TemporalField, ...] = ()
    description: str | None = None
    data_type: str | None = None
    market: str | None = None
    time_granularity: str | None = None
    format_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.dataset_id, "dataset_id")
        _require_text(self.name, "name")
        object.__setattr__(self, "source_ids", _freeze_texts(self.source_ids, "source_ids"))
        if self.uniqueness_rule is not None:
            object.__setattr__(
                self,
                "uniqueness_rule",
                _freeze_texts(self.uniqueness_rule, "uniqueness_rule"),
            )
        if not isinstance(self.temporal_fields, (tuple, list)):
            raise DataDefinitionError("temporal_fields must be a tuple or list of TemporalField values.")
        temporal_fields = tuple(self.temporal_fields)
        if any(not isinstance(field, TemporalField) for field in temporal_fields):
            raise DataDefinitionError("temporal_fields entries must be TemporalField values.")
        object.__setattr__(self, "temporal_fields", temporal_fields)
        if self.description is not None and not isinstance(self.description, str):
            raise DataDefinitionError("description must be a string or None.")
        for field_name in ("data_type", "market", "time_granularity", "format_id"):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, field_name)


@dataclass(frozen=True, slots=True)
class SchemaField:
    """One typed field in a dataset-specific, versioned schema."""

    name: str
    data_type: str
    required: bool = True
    nullable: bool = True
    temporal_role: TemporalFieldRole | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        _require_text(self.data_type, "data_type")
        if type(self.required) is not bool or type(self.nullable) is not bool:
            raise DataDefinitionError("required and nullable must be booleans.")
        if self.temporal_role is not None and not isinstance(
            self.temporal_role,
            TemporalFieldRole,
        ):
            raise DataDefinitionError("temporal_role must be a TemporalFieldRole or None.")


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    """Dataset-specific schema definition, independent of file format and market."""

    schema_id: str
    version: str
    fields: tuple[SchemaField, ...]
    format_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.schema_id, "schema_id")
        _require_text(self.version, "version")
        if self.format_id is not None:
            _require_text(self.format_id, "format_id")
        if not isinstance(self.fields, (tuple, list)) or any(
            not isinstance(field, SchemaField) for field in self.fields
        ):
            raise DataDefinitionError("fields must contain SchemaField values.")
        fields = tuple(self.fields)
        if len({field.name for field in fields}) != len(fields):
            raise DataDefinitionError("Schema field names must be unique.")
        object.__setattr__(self, "fields", fields)


@dataclass(frozen=True, slots=True)
class FetchRequest:
    """Source-agnostic acquisition request with an adapter-owned opaque cursor.

    ``spec`` is normalized to JSON data so the request can be persisted in
    lineage. Credential fields are rejected by the orchestration layer, not
    stored here.
    """

    source_type: str
    spec: Mapping[str, object]
    mode: AcquisitionMode
    cursor: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_type, "source_type")
        if not isinstance(self.spec, Mapping):
            raise DataDefinitionError("FetchRequest spec must be a mapping.")
        if not isinstance(self.mode, AcquisitionMode):
            raise DataDefinitionError("FetchRequest mode must be an AcquisitionMode.")
        if self.cursor is not None:
            _require_text(self.cursor, "cursor")
        frozen: dict[str, object] = {}
        for key, value in self.spec.items():
            _require_text(key, "FetchRequest spec key")
            try:
                encoded = json.dumps(
                    value, sort_keys=True, ensure_ascii=False, allow_nan=False
                )
            except (TypeError, ValueError) as exc:
                raise DataDefinitionError(
                    f"FetchRequest spec value for '{key}' is not JSON-serializable."
                ) from exc
            frozen[key] = json.loads(encoded)
        object.__setattr__(self, "spec", frozen)


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Unparsed response bytes plus cursors named entirely by the adapter."""

    chunks: Iterable[bytes]
    boundary: str
    cursor_start: str | None = None
    cursor_end: str | None = None
    next_cursor: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.boundary, "boundary")
        for field_name in ("cursor_start", "cursor_end", "next_cursor"):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, field_name)
        object.__setattr__(
            self,
            "metadata",
            _freeze_text_pairs(self.metadata, "metadata"),
        )


@dataclass(frozen=True, slots=True)
class AcquisitionRecord:
    """Non-secret metadata describing one successful source import."""

    acquisition_id: str
    source_id: str
    dataset_version: DatasetVersionReference
    mode: AcquisitionMode
    acquired_at: datetime
    cursor_start: str | None = None
    cursor_end: str | None = None
    boundary: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.acquisition_id, "acquisition_id")
        _require_text(self.source_id, "source_id")
        if not isinstance(self.dataset_version, DatasetVersionReference):
            raise DataDefinitionError(
                "dataset_version must be a DatasetVersionReference."
            )
        if not isinstance(self.mode, AcquisitionMode):
            raise DataDefinitionError("mode must be a supported AcquisitionMode.")
        _require_aware_datetime(self.acquired_at, "acquired_at")
        for field_name in ("cursor_start", "cursor_end", "boundary"):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, field_name)
        object.__setattr__(
            self,
            "metadata",
            _freeze_text_pairs(self.metadata, "metadata"),
        )


@dataclass(frozen=True, slots=True)
class DataPartition:
    """Logical partition with an optional immutable content reference.

    The partition ID is scoped to its containing DatasetVersion; event-time
    bounds use the left-closed, right-open interval [start, end).
    """

    partition_id: str
    partition_values: tuple[tuple[str, str], ...] = ()
    event_time_start: datetime | None = None
    event_time_end: datetime | None = None
    record_count: int | None = None
    content_reference: ContentReference | None = None

    def __post_init__(self) -> None:
        _require_text(self.partition_id, "partition_id")
        if self.content_reference is not None and not isinstance(
            self.content_reference,
            ContentReference,
        ):
            raise DataDefinitionError(
                "content_reference must be a ContentReference or None."
            )
        object.__setattr__(
            self,
            "partition_values",
            _freeze_text_pairs(self.partition_values, "partition_values"),
        )
        if self.event_time_start is not None:
            _require_aware_datetime(self.event_time_start, "event_time_start")
        if self.event_time_end is not None:
            _require_aware_datetime(self.event_time_end, "event_time_end")
        _validate_time_range(
            self.event_time_start,
            self.event_time_end,
            "event_time partition",
        )
        partition_keys = tuple(key for key, _ in self.partition_values)
        if len(partition_keys) != len(set(partition_keys)):
            raise DataDefinitionError("partition_values must not contain duplicate keys.")
        if self.record_count is not None and (
            type(self.record_count) is not int or self.record_count < 0
        ):
            raise DataDefinitionError("record_count must be a non-negative integer or None.")


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """Immutable description of one finalized logical dataset state."""

    dataset_id: str
    version_id: str
    created_at: datetime
    data_layer: DataLayer
    partitions: tuple[DataPartition, ...]
    event_time_start: datetime | None = None
    event_time_end: datetime | None = None
    schema_id: str | None = None
    schema_version: str | None = None
    supersedes: DatasetVersionReference | None = None

    def __post_init__(self) -> None:
        _require_text(self.dataset_id, "dataset_id")
        _require_text(self.version_id, "version_id")
        _require_aware_datetime(self.created_at, "created_at")
        if not isinstance(self.data_layer, DataLayer):
            raise DataDefinitionError("data_layer must be a supported DataLayer.")
        if not isinstance(self.partitions, (tuple, list)):
            raise DataDefinitionError("partitions must be a tuple or list of DataPartition values.")
        partitions = tuple(self.partitions)
        if any(not isinstance(partition, DataPartition) for partition in partitions):
            raise DataDefinitionError("partitions entries must be DataPartition values.")
        object.__setattr__(self, "partitions", partitions)
        if self.event_time_start is not None:
            _require_aware_datetime(self.event_time_start, "event_time_start")
        if self.event_time_end is not None:
            _require_aware_datetime(self.event_time_end, "event_time_end")
        _validate_time_range(
            self.event_time_start,
            self.event_time_end,
            "event_time version",
        )
        if (self.schema_id is None) != (self.schema_version is None):
            raise DataDefinitionError("schema_id and schema_version must be provided together.")
        if self.schema_id is not None:
            _require_text(self.schema_id, "schema_id")
            _require_text(self.schema_version, "schema_version")
        if self.supersedes is not None and not isinstance(
            self.supersedes,
            DatasetVersionReference,
        ):
            raise DataDefinitionError("supersedes must be a DatasetVersionReference or None.")

    @property
    def reference(self) -> DatasetVersionReference:
        return DatasetVersionReference(self.dataset_id, self.version_id)

    def validate_content(self, dataset: Dataset) -> None:
        """Validate dataset identity, partition identity, and event-time bounds."""
        if not isinstance(dataset, Dataset):
            raise DatasetVersionValidationError("dataset must be a Dataset.")
        if dataset.dataset_id != self.dataset_id:
            raise DatasetVersionValidationError(
                f"DatasetVersion belongs to '{self.dataset_id}', not '{dataset.dataset_id}'."
            )

        _validate_version_references(self)
        _validate_version_partitions(self)


def _validate_version_references(version: DatasetVersion) -> None:
    if version.supersedes is None:
        return
    if version.supersedes.dataset_id != version.dataset_id:
        raise DatasetVersionValidationError("supersedes must reference the same dataset.")
    if version.supersedes == version.reference:
        raise DatasetVersionValidationError("A DatasetVersion cannot supersede itself.")


def _validate_version_partitions(version: DatasetVersion) -> None:
    partition_ids: set[str] = set()
    partition_keys: set[tuple[tuple[str, str], ...]] = set()
    version_start = version.event_time_start
    version_end = version.event_time_end
    for partition in version.partitions:
        if partition.partition_id in partition_ids:
            raise DatasetVersionValidationError(
                f"Duplicate partition_id '{partition.partition_id}'."
            )
        partition_ids.add(partition.partition_id)

        key = _partition_key(partition.partition_values)
        if key in partition_keys:
            raise DatasetVersionValidationError(f"Duplicate logical partition key {key!r}.")
        partition_keys.add(key)

        if version_start is None:
            continue
        partition_start = partition.event_time_start
        partition_end = partition.event_time_end
        if partition_start is None or partition_end is None:
            raise DatasetVersionValidationError(
                f"Partition '{partition.partition_id}' must declare event-time bounds "
                "when its DatasetVersion declares a range."
            )
        if version_end is None:
            raise DatasetVersionValidationError(
                "DatasetVersion event-time bounds must be provided together."
            )
        if (
            partition_start.astimezone(timezone.utc)
            < version_start.astimezone(timezone.utc)
            or partition_end.astimezone(timezone.utc)
            > version_end.astimezone(timezone.utc)
        ):
            raise DatasetVersionValidationError(
                f"Partition '{partition.partition_id}' falls outside the "
                "DatasetVersion event-time range."
            )


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    """Immutable manifest selecting one explicit source for each logical partition.

    The manifest stores references rather than data and validates against
    caller-supplied versions without accessing a repository or storage.
    """

    snapshot_id: str
    members: tuple[DatasetVersionReference, ...]
    partition_sources: tuple[SnapshotPartitionSource, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.snapshot_id, "snapshot_id")
        if not isinstance(self.members, (tuple, list)):
            raise DataDefinitionError("members must be a tuple or list of DatasetVersionReference values.")
        members = tuple(self.members)
        if any(not isinstance(reference, DatasetVersionReference) for reference in members):
            raise DataDefinitionError("members entries must be DatasetVersionReference values.")
        object.__setattr__(self, "members", members)

        if len(members) != len(set(members)):
            raise DatasetSnapshotError("Snapshot members must not contain duplicate references.")
        if not isinstance(self.partition_sources, (tuple, list)):
            raise DataDefinitionError(
                "partition_sources must be a tuple or list of SnapshotPartitionSource values."
            )
        partition_sources = tuple(self.partition_sources)
        if any(not isinstance(source, SnapshotPartitionSource) for source in partition_sources):
            raise DataDefinitionError(
                "partition_sources entries must be SnapshotPartitionSource values."
            )
        object.__setattr__(self, "partition_sources", partition_sources)

        logical_keys = tuple(source.logical_key for source in partition_sources)
        if len(logical_keys) != len(set(logical_keys)):
            raise DatasetSnapshotError(
                "Each logical partition must have exactly one declared source."
            )
        source_versions = {source.source_version for source in partition_sources}
        if source_versions != set(members):
            raise DatasetSnapshotError(
                "Snapshot members must exactly match the versions used by partition_sources."
            )

    def validate_members(self, versions: tuple[DatasetVersion, ...]) -> None:
        """Validate explicit partition sources against supplied immutable versions."""
        if not isinstance(versions, (tuple, list)):
            raise DatasetSnapshotError("versions must be a tuple or list of DatasetVersion values.")
        candidates = tuple(versions)
        if any(not isinstance(version, DatasetVersion) for version in candidates):
            raise DatasetSnapshotError("versions entries must be DatasetVersion values.")

        versions_by_reference: dict[DatasetVersionReference, DatasetVersion] = {}
        for version in candidates:
            if version.reference in versions_by_reference:
                raise DatasetSnapshotError(
                    f"Candidate versions contain duplicate reference {version.reference!r}."
                )
            versions_by_reference[version.reference] = version

        for member in self.members:
            if member not in versions_by_reference:
                raise DatasetSnapshotError(f"Snapshot member {member!r} was not provided.")

        partitions_by_version: dict[
            DatasetVersionReference,
            dict[str, DataPartition],
        ] = {}
        for member in self.members:
            version = versions_by_reference[member]
            try:
                _validate_version_references(version)
                _validate_version_partitions(version)
            except DatasetVersionValidationError as exc:
                raise DatasetSnapshotError(
                    f"Snapshot member version {member!r} is inconsistent: {exc}"
                ) from exc
            partitions_by_version[version.reference] = {
                partition.partition_id: partition for partition in version.partitions
            }
        for source in self.partition_sources:
            if source.source_version not in self.members:
                raise DatasetSnapshotError(
                    f"Partition source {source.source_version!r} is not a Snapshot member."
                )
            version = versions_by_reference.get(source.source_version)
            if version is None:
                raise DatasetSnapshotError(
                    f"Partition source version {source.source_version!r} was not provided."
                )
            if source.dataset_id != version.dataset_id:
                raise DatasetSnapshotError(
                    "Snapshot partition dataset_id does not match its source version."
                )
            partition = partitions_by_version[source.source_version].get(source.partition_id)
            if partition is None:
                raise DatasetSnapshotError(
                    f"Partition '{source.partition_id}' was not found in "
                    f"version {source.source_version!r}."
                )
            if _partition_key(partition.partition_values) != _partition_key(
                source.partition_values
            ):
                raise DatasetSnapshotError(
                    f"Snapshot logical key for partition '{source.partition_id}' "
                    "does not match its source partition."
                )


@dataclass(frozen=True, slots=True)
class SnapshotPartitionSource:
    """Explicit source for one logical partition in a DatasetSnapshot.

    Logical partition identity is scoped by dataset ID. Source version and
    partition ID select exactly which immutable partition provides its data.
    """

    dataset_id: str
    partition_values: tuple[tuple[str, str], ...]
    source_version: DatasetVersionReference
    partition_id: str

    def __post_init__(self) -> None:
        _require_text(self.dataset_id, "dataset_id")
        _require_text(self.partition_id, "partition_id")
        if not isinstance(self.source_version, DatasetVersionReference):
            raise DataDefinitionError(
                "source_version must be a DatasetVersionReference."
            )
        object.__setattr__(
            self,
            "partition_values",
            _freeze_text_pairs(self.partition_values, "partition_values"),
        )
        keys = tuple(key for key, _ in self.partition_values)
        if len(keys) != len(set(keys)):
            raise DataDefinitionError("partition_values must not contain duplicate keys.")
        if self.dataset_id != self.source_version.dataset_id:
            raise DataDefinitionError(
                "dataset_id must match the source version's dataset_id."
            )

    @property
    def logical_key(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        """Return the dataset-scoped key used to enforce unique snapshot sources."""
        return (self.dataset_id, _partition_key(self.partition_values))


@dataclass(frozen=True, slots=True)
class ProcessingLineage:
    """Immutable record of one transformation's inputs, outputs, and parameters.

    Every listed output is produced by the named operation over the complete
    listed input set. References identify versions only; this object does not
    resolve them or execute the transformation.
    """

    lineage_id: str
    operation_name: str
    operation_version: str
    input_versions: tuple[DatasetVersionReference, ...]
    output_versions: tuple[DatasetVersionReference, ...]
    executed_at: datetime
    parameters: tuple[tuple[str, str | int | float | bool | None], ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.lineage_id, "lineage_id")
        _require_text(self.operation_name, "operation_name")
        _require_text(self.operation_version, "operation_version")
        _require_aware_datetime(self.executed_at, "executed_at")
        for field_name in ("input_versions", "output_versions"):
            values = getattr(self, field_name)
            if not isinstance(values, (tuple, list)):
                raise DataDefinitionError(
                    f"{field_name} must be a tuple or list of DatasetVersionReference values."
                )
            references = tuple(values)
            if not references or any(
                not isinstance(reference, DatasetVersionReference)
                for reference in references
            ):
                raise DataDefinitionError(
                    f"{field_name} must contain at least one DatasetVersionReference."
                )
            if len(references) != len(set(references)):
                raise DataDefinitionError(f"{field_name} must not contain duplicates.")
            object.__setattr__(self, field_name, references)
        if set(self.input_versions) & set(self.output_versions):
            raise DataDefinitionError(
                "A DatasetVersion cannot be both an input and output of the same lineage."
            )
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Quality outcome for a specific data version and rule-set version."""

    report_id: str
    dataset_version: DatasetVersionReference
    rule_set_id: str
    rule_set_version: str
    checked_at: datetime
    status: QualityStatus
    findings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.report_id, "report_id")
        if not isinstance(self.dataset_version, DatasetVersionReference):
            raise DataDefinitionError("dataset_version must be a DatasetVersionReference.")
        _require_text(self.rule_set_id, "rule_set_id")
        _require_text(self.rule_set_version, "rule_set_version")
        _require_aware_datetime(self.checked_at, "checked_at")
        if not isinstance(self.status, QualityStatus):
            raise DataDefinitionError("status must be a supported QualityStatus.")
        object.__setattr__(self, "findings", _freeze_texts(self.findings, "findings"))
