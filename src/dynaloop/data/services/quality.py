"""Lightweight schema-aware quality checks that report without mutating data."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from typing import Protocol

from dynaloop.data.domain.errors import (
    ContentIntegrityError,
    DataDefinitionError,
    DataNotFoundError,
)
from dynaloop.data.domain.models import (
    Dataset,
    DatasetSchema,
    DatasetVersion,
    DatasetVersionReference,
    QualityReport,
    QualityStatus,
    TemporalFieldRole,
)
from dynaloop.data.interfaces.protocols import (
    DataReader,
    DatasetSchemaRepository,
    DatasetVersionRepository,
    QualityReportRepository,
    StorageBackend,
)


class QualityChecker(Protocol):
    """Checker contract for dataset-specific quality policies."""

    @property
    def rule_set_id(self) -> str:
        """Stable identity for the checker rule set."""
        ...

    @property
    def rule_set_version(self) -> str:
        """Version of the checker rules."""
        ...

    def check(
        self,
        dataset: Dataset,
        version: DatasetVersion,
        schema: DatasetSchema | None,
        records: Mapping[str, tuple[Mapping[str, object], ...]],
        storage: StorageBackend,
    ) -> tuple[QualityStatus, tuple[str, ...]]:
        """Return a status and findings without changing the source data."""
        ...


class SchemaQualityChecker:
    """Check schema conformance, uniqueness, event-time bounds, and integrity."""

    def __init__(
        self,
        rule_set_id: str = "schema-integrity",
        version: str = "1",
    ) -> None:
        self._rule_set_id = rule_set_id
        self._version = version

    @property
    def rule_set_id(self) -> str:
        return self._rule_set_id

    @property
    def rule_set_version(self) -> str:
        return self._version

    def check(
        self,
        dataset: Dataset,
        version: DatasetVersion,
        schema: DatasetSchema | None,
        records: Mapping[str, tuple[Mapping[str, object], ...]],
        storage: StorageBackend,
    ) -> tuple[QualityStatus, tuple[str, ...]]:
        findings: list[str] = []
        failures = False

        if schema is None:
            findings.append("WARNING: no schema is registered for this version.")
        else:
            schema_fields = {field.name: field for field in schema.fields}
            event_fields = [
                field.name
                for field in schema.fields
                if field.temporal_role is TemporalFieldRole.EVENT_TIME
            ]
            event_field = event_fields[0] if event_fields else None
            seen_keys: set[tuple[object, ...]] = set()

            for partition in version.partitions:
                partition_records = records.get(partition.partition_id, ())
                previous_event: datetime | date | None = None
                for index, record in enumerate(partition_records, start=1):
                    missing = [
                        field.name
                        for field in schema.fields
                        if field.required and field.name not in record
                    ]
                    if missing:
                        failures = True
                        findings.append(
                            f"FAIL: partition '{partition.partition_id}' record {index} "
                            f"missing required fields {missing!r}."
                        )

                    for field in schema.fields:
                        if field.name not in record:
                            continue
                        value = record[field.name]
                        if value is None:
                            if not field.nullable:
                                failures = True
                                findings.append(
                                    f"FAIL: partition '{partition.partition_id}' record {index} "
                                    f"has null in '{field.name}'."
                                )
                        elif not _matches_type(field.data_type, value):
                            failures = True
                            findings.append(
                                f"FAIL: partition '{partition.partition_id}' record {index} "
                                f"field '{field.name}' is not {field.data_type}."
                            )

                    unexpected = set(record) - set(schema_fields)
                    if unexpected:
                        findings.append(
                            f"WARNING: partition '{partition.partition_id}' record {index} "
                            f"has fields outside schema {sorted(unexpected)!r}."
                        )

                    if dataset.uniqueness_rule:
                        if any(field not in record for field in dataset.uniqueness_rule):
                            failures = True
                            findings.append(
                                f"FAIL: partition '{partition.partition_id}' record {index} "
                                "cannot be checked against the uniqueness rule."
                            )
                        else:
                            key = tuple(
                                _unique_key_value(record[field])
                                for field in dataset.uniqueness_rule
                            )
                            if key in seen_keys:
                                failures = True
                                findings.append(
                                    f"FAIL: duplicate uniqueness key {key!r} in "
                                    f"partition '{partition.partition_id}'."
                                )
                            seen_keys.add(key)

                    if event_field is not None and event_field in record:
                        current = _parse_event_time(record[event_field])
                        if current is None:
                            failures = True
                            findings.append(
                                f"FAIL: partition '{partition.partition_id}' record {index} "
                                "has invalid event time."
                            )
                        else:
                            if (
                                previous_event is not None
                                and _time_comparable(current)
                                < _time_comparable(previous_event)
                            ):
                                failures = True
                                findings.append(
                                    f"FAIL: event time is not ordered in partition "
                                    f"'{partition.partition_id}'."
                                )
                            if not _within_time_bounds(
                                current,
                                partition.event_time_start,
                                partition.event_time_end,
                            ) or not _within_time_bounds(
                                current,
                                version.event_time_start,
                                version.event_time_end,
                            ):
                                failures = True
                                findings.append(
                                    f"FAIL: event time falls outside declared bounds in "
                                    f"partition '{partition.partition_id}'."
                                )
                            previous_event = current

        for partition in version.partitions:
            reference = partition.content_reference
            if reference is None:
                failures = True
                findings.append(
                    f"FAIL: partition '{partition.partition_id}' has no content reference."
                )
                continue
            try:
                verified = storage.verify_content(reference)
            except ContentIntegrityError:
                verified = False
            if not verified:
                failures = True
                findings.append(
                    f"FAIL: partition '{partition.partition_id}' content is missing or corrupt."
                )

        if failures:
            return QualityStatus.FAILED, tuple(findings)
        if findings:
            return QualityStatus.WARNING, tuple(findings)
        return QualityStatus.PASSED, ()


class QualityService:
    """Load a published version, run a checker, and persist its report."""

    def __init__(
        self,
        versions: DatasetVersionRepository,
        schemas: DatasetSchemaRepository,
        reader: DataReader[bytes],
        storage: StorageBackend,
        reports: QualityReportRepository,
        checker: QualityChecker | None = None,
    ) -> None:
        self._versions = versions
        self._schemas = schemas
        self._reader = reader
        self._storage = storage
        self._reports = reports
        self._checker = checker or SchemaQualityChecker()

    def with_checker(self, checker: QualityChecker) -> QualityService:
        """Return a call-scoped service using another checker implementation."""
        return QualityService(
            self._versions,
            self._schemas,
            self._reader,
            self._storage,
            self._reports,
            checker,
        )

    def check_version(
        self,
        dataset: Dataset,
        reference: DatasetVersionReference,
    ) -> QualityReport:
        version = self._versions.get(reference)
        if version is None:
            raise DataNotFoundError(f"Dataset version {reference!r} is not published.")
        if version.dataset_id != dataset.dataset_id:
            raise DataDefinitionError("Dataset and version identities do not match.")

        schema = None
        if version.schema_id is not None and version.schema_version is not None:
            schema = self._schemas.get(version.schema_id, version.schema_version)
        records = (
            {
                partition.partition_id: _read_json_lines(
                    self._reader.read_partition(reference, partition.partition_id),
                    partition.partition_id,
                )
                for partition in version.partitions
            }
            if schema is not None
            else {}
        )
        status, findings = self._checker.check(
            dataset,
            version,
            schema,
            records,
            self._storage,
        )
        report = QualityReport(
            report_id=uuid.uuid4().hex,
            dataset_version=reference,
            rule_set_id=self._checker.rule_set_id,
            rule_set_version=self._checker.rule_set_version,
            checked_at=datetime.now(timezone.utc),
            status=status,
            findings=findings,
        )
        self._reports.save(report)
        return report


def _read_json_lines(
    chunks: Iterable[bytes],
    partition_id: str,
) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    line_number = 0
    try:
        for line_number, raw_line in enumerate(
            b"".join(chunks).splitlines(),
            start=1,
        ):
            if not raw_line:
                continue
            record = json.loads(raw_line)
            if not isinstance(record, dict):
                raise ValueError("record must be a JSON object")
            records.append(record)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        location = f" on line {line_number}" if line_number else ""
        raise DataDefinitionError(
            f"Partition '{partition_id}' is not valid JSON Lines{location}."
        ) from exc
    return tuple(records)


def _matches_type(data_type: str, value: object) -> bool:
    if data_type == "string":
        return isinstance(value, str)
    if data_type == "integer":
        return type(value) is int
    if data_type == "number":
        return type(value) in (int, float)
    if data_type == "boolean":
        return type(value) is bool
    if data_type == "date":
        return _parse_date(value) is not None
    if data_type == "datetime":
        return _parse_datetime(value) is not None
    if data_type == "json":
        return True
    return False


def _parse_event_time(value: object) -> datetime | date | None:
    parsed_datetime = _parse_datetime(value)
    if parsed_datetime is not None:
        return parsed_datetime
    return _parse_date(value)


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.utcoffset() is not None else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _time_comparable(value: datetime | date) -> datetime | date:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return value


def _within_time_bounds(
    value: datetime | date,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    if start is None or end is None:
        return True
    if isinstance(value, datetime):
        instant = value.astimezone(timezone.utc)
        return start.astimezone(timezone.utc) <= instant < end.astimezone(timezone.utc)
    start_date = start.astimezone(timezone.utc).date()
    end_date = end.astimezone(timezone.utc).date()
    return start_date <= value < end_date


def _unique_key_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return value
