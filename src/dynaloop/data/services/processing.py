"""Small record-standardization and versioned processing primitives."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TypeAlias

from dynaloop.data.domain.errors import DataDefinitionError, DataNotFoundError
from dynaloop.data.domain.models import (
    Dataset,
    DatasetSchema,
    DatasetVersion,
    DatasetVersionReference,
    ProcessingLineage,
    SchemaField,
)
from dynaloop.data.interfaces.protocols import (
    DatasetSchemaRepository,
    DatasetVersionRepository,
    DataReader,
    ProcessingLineageRepository,
)
from dynaloop.data.services.publishing import DatasetVersionPublishingService


Record: TypeAlias = Mapping[str, object]
RecordSet: TypeAlias = tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class StandardizationResult:
    """Normalized records plus explicit warnings about configured row handling."""

    records: RecordSet
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessingOutput:
    """Definition and publication precondition for one processed DatasetVersion."""

    dataset: Dataset
    version: DatasetVersion
    expected_head: DatasetVersionReference | None


def standardize_records(
    records: Iterable[Record],
    schema: DatasetSchema,
    *,
    null_policy: str = "preserve",
    unique_fields: tuple[str, ...] = (),
    duplicate_policy: str = "reject",
    sort_time_field: str | None = None,
) -> StandardizationResult:
    """Normalize scalar values using a dataset schema and explicit row policies.

    Supported field types are ``string``, ``integer``, ``number``, ``boolean``,
    ``date``, ``datetime``, and ``json``. Dropped records are only possible with
    the explicit ``null_policy='drop_record'`` policy and are reported.
    """
    if null_policy not in ("preserve", "reject", "drop_record"):
        raise DataDefinitionError("Unsupported null_policy.")
    if duplicate_policy not in ("allow", "reject", "keep_first", "keep_last"):
        raise DataDefinitionError("Unsupported duplicate_policy.")
    fields = {field.name: field for field in schema.fields}
    if unique_fields and any(field not in fields for field in unique_fields):
        raise DataDefinitionError("unique_fields must refer to declared schema fields.")
    if sort_time_field is not None:
        time_field = fields.get(sort_time_field)
        if time_field is None or time_field.data_type not in ("datetime", "date"):
            raise DataDefinitionError(
                "sort_time_field must name a schema datetime or date field."
            )

    normalized: list[dict[str, object]] = []
    dropped_null_records = 0
    for row_number, raw_record in enumerate(records, 1):
        if not isinstance(raw_record, Mapping):
            raise DataDefinitionError(f"Record {row_number} must be a mapping.")
        record = dict(raw_record)
        missing = [field.name for field in schema.fields if field.required and field.name not in record]
        if missing:
            raise DataDefinitionError(
                f"Record {row_number} is missing required fields {missing!r}."
            )

        has_forbidden_null = False
        for field in schema.fields:
            if field.name not in record:
                continue
            value = record[field.name]
            if value is None:
                if null_policy == "drop_record":
                    has_forbidden_null = True
                    break
                if not field.nullable:
                    raise DataDefinitionError(
                        f"Record {row_number} has null in non-nullable field '{field.name}'."
                    )
                if null_policy == "reject":
                    raise DataDefinitionError(
                        f"Record {row_number} has null in field '{field.name}'."
                    )
                continue
            record[field.name] = _normalize_value(field, value, row_number)
        if has_forbidden_null:
            dropped_null_records += 1
            continue
        normalized.append(record)

    duplicate_count = 0
    if unique_fields:
        keys: dict[tuple[object, ...], int] = {}
        filtered: list[dict[str, object]] = []
        for record in normalized:
            key = tuple(record.get(field) for field in unique_fields)
            if key not in keys:
                keys[key] = len(filtered)
                filtered.append(record)
                continue
            duplicate_count += 1
            if duplicate_policy == "reject":
                raise DataDefinitionError(
                    f"Duplicate record for unique fields {unique_fields!r}: {key!r}."
                )
            if duplicate_policy == "keep_last":
                filtered[keys[key]] = record
            elif duplicate_policy == "allow":
                filtered.append(record)
        normalized = filtered

    if sort_time_field is not None:
        def sort_value(item: dict[str, object]) -> str:
            value = item.get(sort_time_field)
            if not isinstance(value, str):
                raise DataDefinitionError(
                    f"Record is missing normalized time field '{sort_time_field}'."
                )
            return value

        normalized.sort(key=sort_value)
    warnings: list[str] = []
    if dropped_null_records:
        warnings.append(f"Dropped {dropped_null_records} records by explicit null policy.")
    if duplicate_count and duplicate_policy in ("keep_first", "keep_last"):
        warnings.append(
            f"Resolved {duplicate_count} duplicate records using '{duplicate_policy}'."
        )
    return StandardizationResult(tuple(normalized), tuple(warnings))


def align_records_by_time(
    records_by_source: Mapping[str, Iterable[Record]],
    time_field: str,
) -> tuple[tuple[str, tuple[tuple[str, dict[str, object] | None], ...]], ...]:
    """Outer-align records by an explicit temporal field without dropping rows."""
    if not isinstance(time_field, str) or not time_field.strip():
        raise DataDefinitionError("time_field must be a non-empty string.")
    aligned: dict[str, dict[str, dict[str, object] | None]] = {}
    source_ids = tuple(records_by_source)
    if len(source_ids) != len(set(source_ids)):
        raise DataDefinitionError("Source identifiers must be unique.")
    for source_id, records in records_by_source.items():
        for index, raw_record in enumerate(records, 1):
            if not isinstance(raw_record, Mapping) or time_field not in raw_record:
                raise DataDefinitionError(
                    f"Record {index} from '{source_id}' lacks '{time_field}'."
                )
            key = _time_key(raw_record[time_field])
            row_map = aligned.setdefault(key, {key_id: None for key_id in source_ids})
            if row_map[source_id] is not None:
                raise DataDefinitionError(
                    f"Source '{source_id}' has duplicate records at {key}."
                )
            row_map[source_id] = dict(raw_record)
    return tuple(
        (
            key,
            tuple((source_id, rows[source_id]) for source_id in source_ids),
        )
        for key, rows in sorted(aligned.items())
    )


class ProcessingService:
    """Publish outputs from a caller-selected processor and persist its lineage."""

    def __init__(
        self,
        versions: DatasetVersionRepository,
        reader: DataReader[bytes],
        schemas: DatasetSchemaRepository,
        publisher: DatasetVersionPublishingService,
        lineages: ProcessingLineageRepository,
    ) -> None:
        self._versions = versions
        self._reader = reader
        self._schemas = schemas
        self._publisher = publisher
        self._lineages = lineages

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
        """Execute a pure transform, standardize all outputs, then publish them."""
        if not outputs:
            raise DataDefinitionError("Processing requires at least one output.")
        input_records = {
            reference: self._read_json_lines(reference)
            for reference in input_versions
        }
        produced = transform(input_records)
        targets = {output.dataset.dataset_id: output for output in outputs}
        if set(produced) != set(targets):
            raise DataDefinitionError(
                "Processor outputs must exactly match configured output Dataset IDs."
            )

        published_refs: list[DatasetVersionReference] = []
        for dataset_id, output in targets.items():
            schema_id = output.version.schema_id
            schema_version = output.version.schema_version
            if schema_id is None or schema_version is None:
                raise DataDefinitionError(
                    f"Processed output '{dataset_id}' must declare a schema."
                )
            schema = self._schemas.get(schema_id, schema_version)
            if schema is None:
                raise DataNotFoundError(
                    f"Schema '{schema_id}@{schema_version}' was not found."
                )
            records_by_partition = produced[dataset_id]
            expected_ids = {partition.partition_id for partition in output.version.partitions}
            if set(records_by_partition) != expected_ids:
                raise DataDefinitionError(
                    f"Processor partitions for '{dataset_id}' do not match its output version."
                )
            contents: dict[str, tuple[bytes, ...]] = {}
            for partition_id, records in records_by_partition.items():
                standardized = standardize_records(records, schema)
                content = b"".join(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                    + b"\n"
                    for record in standardized.records
                )
                contents[partition_id] = (content,)
            published_refs.append(
                self._publisher.publish_version(
                    output.dataset,
                    output.version,
                    output.expected_head,
                    contents,
                )
            )

        lineage = ProcessingLineage(
            lineage_id=lineage_id,
            operation_name=operation_name,
            operation_version=operation_version,
            input_versions=input_versions,
            output_versions=tuple(published_refs),
            executed_at=datetime.now(timezone.utc),
            parameters=parameters,
        )
        self._lineages.save(lineage)
        return lineage

    def _read_json_lines(
        self,
        reference: DatasetVersionReference,
    ) -> RecordSet:
        version = self._versions.get(reference)
        if version is None:
            raise DataNotFoundError(f"Input version {reference!r} is not published.")
        rows: list[dict[str, object]] = []
        for partition in version.partitions:
            if partition.content_reference is None:
                raise DataDefinitionError(
                    f"Input partition '{partition.partition_id}' has no content."
                )
            raw_bytes = b"".join(
                self._reader.read_partition(reference, partition.partition_id)
            )
            line_number = 0
            try:
                for line_number, line in enumerate(raw_bytes.splitlines(), 1):
                    if not line:
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("record must be a JSON object")
                    rows.append(value)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise DataDefinitionError(
                    f"Input version {reference!r} is not valid JSON Lines "
                    f"(line {line_number})."
                ) from exc
        return tuple(rows)


def _normalize_value(field: SchemaField, value: object, row_number: int) -> object:
    try:
        if field.data_type == "string":
            if isinstance(value, (dict, list)):
                raise ValueError("expected scalar string")
            return str(value)
        if field.data_type == "integer":
            if isinstance(value, bool):
                raise ValueError("boolean is not an integer field value")
            if not isinstance(value, (str, int, float)):
                raise ValueError("expected a string or number for an integer field")
            return int(value)
        if field.data_type == "number":
            if isinstance(value, bool):
                raise ValueError("boolean is not a number field value")
            if not isinstance(value, (str, int, float)):
                raise ValueError("expected a string or number for a number field")
            number = float(value)
            if not (number == number and abs(number) != float("inf")):
                raise ValueError("number must be finite")
            return number
        if field.data_type == "boolean":
            if type(value) is bool:
                return value
            if isinstance(value, str) and value.lower() in ("true", "false"):
                return value.lower() == "true"
            raise ValueError("expected boolean or 'true'/'false'")
        if field.data_type == "datetime":
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            if parsed.utcoffset() is None:
                raise ValueError("datetime must include a timezone")
            return parsed.astimezone(timezone.utc).isoformat()
        if field.data_type == "date":
            parsed_date = value if isinstance(value, date) else date.fromisoformat(str(value))
            if isinstance(parsed_date, datetime):
                raise ValueError("expected a date without time")
            return parsed_date.isoformat()
        if field.data_type == "json":
            if isinstance(value, (dict, list, int, float, bool)) or value is None:
                return value
            return json.loads(str(value))
        raise DataDefinitionError(f"Unsupported schema data_type '{field.data_type}'.")
    except (TypeError, ValueError, OverflowError) as exc:
        raise DataDefinitionError(
            f"Record {row_number} field '{field.name}' cannot be normalized "
            f"as {field.data_type}."
        ) from exc


def _time_key(value: object) -> str:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise DataDefinitionError("Time alignment requires timezone-aware values.")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return _time_key(datetime.fromisoformat(value))
        except ValueError:
            try:
                return date.fromisoformat(value).isoformat()
            except ValueError as exc:
                raise DataDefinitionError("Invalid time alignment value.") from exc
    raise DataDefinitionError("Time alignment values must be date/datetime values.")
