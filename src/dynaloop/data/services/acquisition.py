"""Source-agnostic acquisition with pluggable source and format adapters."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
from collections import Counter
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from dynaloop.data.domain.errors import DataDefinitionError
from dynaloop.data.domain.models import (
    AcquisitionMode,
    AcquisitionRecord,
    DataSource,
    DataPartition,
    Dataset,
    DatasetVersion,
    DatasetVersionReference,
    FetchRequest,
    FetchResult,
)
from dynaloop.data.interfaces.protocols import (
    AcquisitionRepository,
    DataSourceRepository,
    FormatAdapter,
    SourceAdapter,
)
from dynaloop.data.services.acquisition_spec import normalize_spec
from dynaloop.data.services.adapter_registry import AdapterRegistry
from dynaloop.data.services.publishing import DatasetVersionPublishingService


class LocalFileAcquisitionAdapter:
    """Read arbitrary local file bytes with batch or explicit offset cursors."""

    source_type = "local_file"
    adapter_version = "1.0"
    supported_modes = frozenset(
        (AcquisitionMode.BATCH, AcquisitionMode.INCREMENTAL)
    )
    capabilities = frozenset({"seekable", "replayable"})

    def __init__(self, chunk_size: int = 1024 * 1024) -> None:
        if type(chunk_size) is not int or chunk_size <= 0:
            raise DataDefinitionError("chunk_size must be a positive integer.")
        self._chunk_size = chunk_size

    def read(
        self,
        path: str | Path,
        mode: AcquisitionMode,
        cursor: str | None = None,
    ) -> tuple[Iterable[bytes], str, str]:
        """Return chunks and the exact start/end byte offsets used."""
        if mode not in self.supported_modes:
            raise DataDefinitionError(f"Local files do not support mode '{mode.value}'.")
        file_path = Path(path).expanduser()
        if not file_path.is_file():
            raise DataDefinitionError(f"Acquisition file '{file_path}' does not exist.")
        if mode is AcquisitionMode.BATCH:
            if cursor is not None:
                raise DataDefinitionError("Batch import does not accept an offset cursor.")
            start = 0
        else:
            if cursor is None or not cursor.isdecimal():
                raise DataDefinitionError(
                    "Incremental file import requires a non-negative byte-offset cursor."
                )
            start = int(cursor)
            if start > file_path.stat().st_size:
                raise DataDefinitionError("Incremental cursor exceeds the file size.")
        end = file_path.stat().st_size

        def chunks() -> Iterator[bytes]:
            with file_path.open("rb") as stream:
                stream.seek(start)
                while chunk := stream.read(self._chunk_size):
                    yield chunk

        return chunks(), str(start), str(end)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Interpret the opaque cursor as a byte offset for local files."""
        if request.source_type != self.source_type:
            raise DataDefinitionError(
                f"Local file adapter cannot handle source type '{request.source_type}'."
            )
        raw_path = request.spec.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise DataDefinitionError("Local file requests require a 'path' spec value.")
        chunks, start, end = self.read(raw_path, request.mode, request.cursor)
        if request.mode is AcquisitionMode.INCREMENTAL:
            return FetchResult(
                chunks=chunks,
                boundary=f"byte-offset:{start}",
                cursor_start=start,
                cursor_end=end,
                next_cursor=end,
                metadata=(("transport", "local-file"),),
            )
        return FetchResult(
            chunks=chunks,
            boundary="byte-offset:0",
            metadata=(("transport", "local-file"),),
        )


class CsvFormatAdapter:
    """Decode header-based CSV, preserving cell text; profiling is advisory."""

    format_id = "csv"
    adapter_version = "1.0"
    supported_modes = frozenset((AcquisitionMode.BATCH,))
    ENCODINGS = {"auto", "utf-8", "utf-8-sig", "utf-16", "gb18030", "cp1252"}
    DELIMITERS = {"auto", ",", ";", "\t", "|"}

    def __init__(self, *, encoding: str = "auto", delimiter: str = "auto",
                 missing_policy: str = "common") -> None:
        if encoding not in self.ENCODINGS:
            raise DataDefinitionError("Unsupported CSV encoding.")
        if delimiter not in self.DELIMITERS:
            raise DataDefinitionError("Unsupported CSV delimiter.")
        if missing_policy not in {"common", "blank"}:
            raise DataDefinitionError("missing_policy must be common or blank.")
        self._encoding = encoding
        self._delimiter = delimiter
        self._missing_policy = missing_policy
        self.resolved_encoding = encoding
        self.resolved_delimiter = delimiter

    def convert(self, chunks: Iterable[bytes], mode: AcquisitionMode) -> tuple[bytes, int]:
        _, records = self._read_records(chunks, mode)
        content = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                          for row in records).encode("utf-8")
        return content, len(records)

    def decode(
        self, chunks: Iterable[bytes], mode: AcquisitionMode
    ) -> tuple[bytes, int]:
        """Satisfy the generic FormatAdapter protocol."""
        return self.convert(chunks, mode)

    def preview(self, chunks: Iterable[bytes], mode: AcquisitionMode, *,
                sample_size: int = 5) -> CsvPreview:
        fields, records = self._read_records(chunks, mode)
        return _build_csv_preview(fields, records, sample_size, self._missing_policy)

    def preview_records(self, records: Iterable[Mapping[str, object]], *,
                        sample_size: int = 5) -> CsvPreview:
        rows = list(records)
        if not rows:
            return _build_csv_preview((), [], sample_size, self._missing_policy)
        if not isinstance(rows[0], Mapping):
            raise DataDefinitionError("Stored CSV records must be mappings.")
        fields = tuple(rows[0])
        if not fields or any(not isinstance(name, str) or not name.strip() for name in fields):
            raise DataDefinitionError("Stored CSV records do not have valid field names.")
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != set(fields):
                raise DataDefinitionError("Stored CSV records do not share the same fields.")
            if any(value is not None and not isinstance(value, str) for value in row.values()):
                raise DataDefinitionError("Stored CSV values must be text or null.")
        return _build_csv_preview(fields, rows, sample_size, self._missing_policy)

    def _read_records(self, chunks: Iterable[bytes], mode: AcquisitionMode
                      ) -> tuple[Sequence[str], list[dict[str, str | None]]]:
        if mode not in self.supported_modes:
            raise DataDefinitionError(f"CSV format adapter does not support mode '{mode.value}'.")
        raw = b"".join(chunks)
        encoding = self._encoding
        if encoding == "auto":
            # Only BOM/UTF-8 detection is unambiguous. Legacy encodings require selection.
            encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            text = raw.decode(encoding).removeprefix("\ufeff")
        except UnicodeError as exc:
            raise DataDefinitionError(
                "CSV decoding failed. Select UTF-8, UTF-16, GB18030 or Windows-1252 explicitly."
            ) from exc
        if "\x00" in text:
            raise DataDefinitionError("CSV contains NUL bytes; check the selected encoding.")
        delimiter = self._delimiter
        if delimiter == "auto":
            # Parse the first logical header with each candidate: avoids Sniffer failing
            # on a truncated sample, missing cells or quoted multiline records.
            candidates = []
            for candidate in (",", ";", "\t", "|"):
                try:
                    header = next(csv.reader(io.StringIO(text, newline=""),
                                             delimiter=candidate, strict=True), [])
                    candidates.append((len(header), candidate))
                except csv.Error:
                    continue
            if not candidates:
                raise DataDefinitionError("Malformed CSV header quoting.")
            width = max(count for count, _ in candidates)
            winners = [d for count, d in candidates if count == width]
            if width > 1 and len(winners) != 1:
                raise DataDefinitionError("Ambiguous CSV delimiter; select it explicitly.")
            delimiter = winners[0] if width > 1 else ","
        self.resolved_encoding, self.resolved_delimiter = encoding, delimiter
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        try:
            fields = next(reader, [])
            if not fields or any(not name.strip() for name in fields):
                raise DataDefinitionError("CSV input requires non-empty header names.")
            if len({name.strip() for name in fields}) != len(fields):
                raise DataDefinitionError("CSV input requires unique header names.")
            records = []
            for row in reader:
                if not row:
                    continue
                if len(row) > len(fields):
                    raise DataDefinitionError(f"CSV row {reader.line_num} has more cells than its header.")
                records.append(dict(zip(fields, row + [None] * (len(fields) - len(row)))))
        except csv.Error as exc:
            raise DataDefinitionError(f"Malformed CSV near line {reader.line_num}: {exc}") from exc
        return fields, records


class KlineJsonFormatAdapter:
    """Decode a K-line JSON response into tabular OHLCV records.

    The output uses the same JSON-lines record layout as CsvFormatAdapter, so
    preview, column distributions, and the quality gate work with no changes.
    Empty or malformed payloads are rejected instead of publishing an empty
    version.
    """

    format_id = "kline-json"
    adapter_version = "1.1"
    supported_modes = frozenset((AcquisitionMode.BATCH,))
    COLUMNS = ("date", "open", "close", "high", "low", "volume")
    # Tencent fqkline/get names its row array after frequency + adjustment:
    # ``day`` / ``qfqday`` / ``hfqday``, and the same suffixes for week / month.
    # A weekly or hfq request used to be rejected as "no daily rows".
    ROW_KEYS = (
        "qfqday", "hfqday", "day",
        "qfqweek", "hfqweek", "week",
        "qfqmonth", "hfqmonth", "month",
    )

    def __init__(self, *, missing_policy: str = "common") -> None:
        self._preview_adapter = CsvFormatAdapter(missing_policy=missing_policy)

    def convert(
        self, chunks: Iterable[bytes], mode: AcquisitionMode
    ) -> tuple[bytes, int]:
        records = self._records(chunks, mode)
        content = "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in records
        ).encode("utf-8")
        return content, len(records)

    def decode(
        self, chunks: Iterable[bytes], mode: AcquisitionMode
    ) -> tuple[bytes, int]:
        """Satisfy the generic FormatAdapter protocol."""
        return self.convert(chunks, mode)

    def preview(
        self, chunks: Iterable[bytes], mode: AcquisitionMode, *,
        sample_size: int = 5,
    ) -> CsvPreview:
        return self._preview_adapter.preview_records(
            self._records(chunks, mode), sample_size=sample_size
        )

    def preview_records(
        self, records: Iterable[Mapping[str, object]], *, sample_size: int = 5
    ) -> CsvPreview:
        return self._preview_adapter.preview_records(records, sample_size=sample_size)

    def _records(
        self, chunks: Iterable[bytes], mode: AcquisitionMode
    ) -> list[dict[str, str | None]]:
        if mode not in self.supported_modes:
            raise DataDefinitionError(
                f"K-line JSON adapter does not support mode '{mode.value}'."
            )
        raw = b"".join(chunks)
        if not raw.strip():
            raise DataDefinitionError(
                "K-line JSON response is empty; refusing to publish an empty version."
            )
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DataDefinitionError(
                "K-line response is not valid JSON; use Raw bytes to freeze it as-is."
            ) from exc
        if not isinstance(payload, dict):
            raise DataDefinitionError("K-line JSON must be an object.")
        if payload.get("code") not in (0, "0", None):
            raise DataDefinitionError(
                f"K-line API returned an error: {payload.get('msg') or payload.get('code')}."
            )
        data = payload.get("data")
        if not isinstance(data, dict) or not data:
            raise DataDefinitionError(
                "K-line JSON has no data payload; refusing to publish an empty version."
            )
        series = next(
            (value for value in data.values() if isinstance(value, dict)), None
        )
        if series is None:
            raise DataDefinitionError("K-line JSON contains no symbol series.")
        row_key = next(
            (
                key
                for key in self.ROW_KEYS
                if isinstance(series.get(key), list) and series[key]
            ),
            None,
        )
        if row_key is None:
            empty_arrays = sorted(
                key for key, value in series.items() if isinstance(value, list)
            )
            if empty_arrays:
                raise DataDefinitionError(
                    "K-line API returned no rows for this symbol and time window "
                    f"(empty series: {', '.join(empty_arrays)}). Check the symbol, "
                    "date range (start must precede end) and frequency."
                )
            raise DataDefinitionError(
                "K-line JSON has no OHLCV row series; refusing to publish an empty version."
            )
        rows = series[row_key]
        records: list[dict[str, str | None]] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < len(self.COLUMNS):
                raise DataDefinitionError(
                    "Each K-line row must provide date/open/close/high/low/volume."
                )
            records.append(
                {
                    name: None if value is None else str(value)
                    for name, value in zip(self.COLUMNS, row[: len(self.COLUMNS)])
                }
            )
        return records


@dataclass(frozen=True, slots=True)
class CsvColumnSummary:
    name: str
    inferred_type: str
    observed_count: int
    missing_count: int
    minimum: float | str | None = None
    mean: float | None = None
    standard_deviation: float | None = None
    maximum: float | str | None = None
    distinct_count: int = 0
    top_values: tuple[tuple[str, int], ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CsvPreview:
    row_count: int
    columns: tuple[CsvColumnSummary, ...]
    preview_rows: tuple[tuple[str | None, ...], ...]
    preview_truncated: bool
    missing_policy: str = "common"


def _build_csv_preview(fieldnames, records, sample_size, missing_policy="common") -> CsvPreview:
    if type(sample_size) is not int or not 0 <= sample_size <= 100:
        raise DataDefinitionError("sample_size must be an integer between 0 and 100.")
    fields = tuple(fieldnames)
    return CsvPreview(
        len(records),
        tuple(_summarize_csv_column(name, tuple(row.get(name) for row in records), missing_policy)
              for name in fields),
        tuple(tuple(row.get(name) for name in fields) for row in records[:sample_size]),
        len(records) > sample_size, missing_policy,
    )


def _summarize_csv_column(name: str, values: tuple[str | None, ...],
                          missing_policy: str = "common") -> CsvColumnSummary:
    tokens = {"", ".", "na", "n/a", "nan", "null", "none"} if missing_policy == "common" else {""}
    observed = tuple(v for v in values if v is not None and v.strip().casefold() not in tokens)
    counts = Counter(observed)
    base = dict(name=name, observed_count=len(observed), missing_count=len(values)-len(observed),
                distinct_count=len(counts), top_values=tuple(counts.most_common(5)))
    if not observed:
        return CsvColumnSummary(inferred_type="empty", **base)
    stripped = [v.strip() for v in observed]
    # Leading zeroes and long integer strings are identifier-like; do not round them.
    if any(re.fullmatch(r"[+-]?0\d+", v) or
           (re.fullmatch(r"[+-]?\d+", v) and len(v.lstrip("+-")) > 15) for v in stripped):
        return CsvColumnSummary(inferred_type="text", notes=("Identifier-like integers preserved as text.",), **base)
    if all(v.casefold() in {"true", "false"} for v in stripped):
        return CsvColumnSummary(inferred_type="boolean", **base)
    numbers = []
    for v in stripped:
        try:
            # Deliberately exclude locale/grouping/currency/percentage interpretation.
            if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", v):
                continue
            number = float(v)
            if math.isfinite(number):
                numbers.append(number)
        except ValueError:
            pass
    if len(numbers) == len(observed):
        try:
            mean = statistics.mean(numbers)
            deviation = statistics.stdev(numbers) if len(numbers) > 1 else None
            if not math.isfinite(mean) or (deviation is not None and not math.isfinite(deviation)):
                raise OverflowError
            return CsvColumnSummary(inferred_type="number", minimum=min(numbers), maximum=max(numbers),
                                    mean=mean, standard_deviation=deviation, **base)
        except (OverflowError, ValueError):
            return CsvColumnSummary(inferred_type="number", minimum=min(numbers), maximum=max(numbers),
                                    notes=("Numeric range too large for finite summary statistics.",), **base)
    try:
        if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in stripped):
            dates = [date.fromisoformat(v) for v in stripped]
            return CsvColumnSummary(inferred_type="date", minimum=min(dates).isoformat(),
                                    maximum=max(dates).isoformat(), **base)
        if all(re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", v) for v in stripped):
            times = [datetime.fromisoformat(v.replace("Z", "+00:00")) for v in stripped]
            aware = [t.utcoffset() is not None for t in times]
            if len(set(aware)) > 1:
                raise ValueError("Mixed timezone awareness")
            times = [t.astimezone(timezone.utc) for t in times] if all(aware) else times
            return CsvColumnSummary(inferred_type="datetime", minimum=min(times).isoformat(),
                                    maximum=max(times).isoformat(), **base)
    except ValueError:
        pass
    return CsvColumnSummary(
        inferred_type="mixed" if numbers else "text",
        notes=("Mixed numeric/non-numeric values; numeric statistics withheld.",) if numbers else (),
        **base,
    )


class AcquisitionService:
    """Coordinate source-agnostic acquisition, publishing and lineage."""

    def __init__(
        self,
        sources: DataSourceRepository,
        acquisitions: AcquisitionRepository,
        publisher: DatasetVersionPublishingService,
        file_adapter: LocalFileAcquisitionAdapter | None = None,
        source_registry: AdapterRegistry[Any] | None = None,
        format_registry: AdapterRegistry[Any] | None = None,
    ) -> None:
        self._sources = sources
        self._acquisitions = acquisitions
        self._publisher = publisher
        self._file_adapter = file_adapter or LocalFileAcquisitionAdapter()
        if source_registry is None or format_registry is None:
            # Imported lazily: the default registry factories need these classes.
            from dynaloop.data.services.default_adapters import (
                build_default_registries,
            )

            built_sources, built_formats = build_default_registries(
                file_adapter=self._file_adapter
            )
            source_registry = source_registry if source_registry is not None else built_sources
            format_registry = format_registry if format_registry is not None else built_formats
        self._source_registry = source_registry
        self._format_registry = format_registry

    @property
    def source_registry(self) -> AdapterRegistry[Any]:
        return self._source_registry

    @property
    def format_registry(self) -> AdapterRegistry[Any]:
        return self._format_registry

    def use_registries(
        self,
        source_registry: AdapterRegistry[Any],
        format_registry: AdapterRegistry[Any],
    ) -> None:
        """Replace both registries so catalog views and imports stay consistent."""
        self._source_registry = source_registry
        self._format_registry = format_registry

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
    ) -> DatasetVersionReference:
        """Backwards-compatible wrapper over the source-agnostic path."""
        if not isinstance(files, Mapping) or not files:
            raise DataDefinitionError("files must map partition IDs to local paths.")
        requests = {
            partition_id: FetchRequest(
                source_type=LocalFileAcquisitionAdapter.source_type,
                spec={"path": str(path)},
                mode=mode,
                cursor=cursor,
            )
            for partition_id, path in files.items()
        }
        return self.import_source(
            source_id,
            dataset,
            version,
            expected_head,
            requests,
            format_adapter=csv_adapter,
            source_adapter=self._file_adapter,
            acquisition_id=acquisition_id,
        )

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
    ) -> DatasetVersionReference:
        """Fetch, optionally decode, and publish bytes from any registered source.

        The core recognizes only raw bytes, opaque cursors and lineage. Paging,
        authentication, transport and response shape belong to the adapter.
        """
        if not isinstance(dataset, Dataset) or not isinstance(version, DatasetVersion):
            raise DataDefinitionError("dataset and version must be domain values.")
        if source_id not in dataset.source_ids:
            raise DataDefinitionError(
                f"Dataset '{dataset.dataset_id}' is not associated with source '{source_id}'."
            )
        source = self._sources.get(source_id)
        if not isinstance(source, DataSource):
            raise DataDefinitionError(f"Data source '{source_id}' is not registered.")
        if not isinstance(requests, Mapping) or not requests:
            raise DataDefinitionError(
                "requests must map partition IDs to FetchRequest values."
            )
        modes: set[AcquisitionMode] = set()
        for partition_id, request in requests.items():
            if not isinstance(partition_id, str) or not partition_id.strip():
                raise DataDefinitionError("Partition IDs must be non-empty strings.")
            if not isinstance(request, FetchRequest):
                raise DataDefinitionError("Each request must be a FetchRequest.")
            modes.add(request.mode)
        if len(modes) != 1:
            raise DataDefinitionError(
                "All partitions in one import must use the same acquisition mode."
            )
        mode = next(iter(modes))
        if mode is AcquisitionMode.INCREMENTAL and len(requests) != 1:
            raise DataDefinitionError(
                "Incremental import currently requires exactly one partition file."
            )

        decoder = format_adapter
        if decoder is None and format_id:
            decoder = self._format_registry.create(format_id)
        if decoder is not None and mode not in decoder.supported_modes:
            raise DataDefinitionError(
                f"Format adapter does not support mode '{mode.value}'."
            )

        contents: dict[str, Iterable[bytes]] = {}
        row_counts: dict[str, int] = {}
        start_cursor: str | None = None
        end_cursor: str | None = None
        boundary: str | None = None
        spec_pairs: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        adapter_labels: set[str] = set()
        extra_metadata: list[tuple[str, str]] = []
        has_pages = False
        for partition_id, request in requests.items():
            spec_pairs.append((partition_id, normalize_spec(request.spec)))
            adapter = (
                source_adapter
                if source_adapter is not None
                else self._source_registry.create(request.source_type)
            )
            if not isinstance(adapter, SourceAdapter):
                raise DataDefinitionError(
                    f"Registered source '{request.source_type}' does not satisfy SourceAdapter."
                )
            if adapter.source_type != request.source_type:
                raise DataDefinitionError(
                    f"Source adapter identity mismatch for '{request.source_type}'."
                )
            if mode not in adapter.supported_modes:
                raise DataDefinitionError(
                    f"Source adapter '{request.source_type}' does not support mode '{mode.value}'."
                )
            result = adapter.fetch(request)
            if not isinstance(result, FetchResult):
                raise DataDefinitionError("SourceAdapter.fetch must return a FetchResult.")
            if decoder is None:
                contents[partition_id] = result.chunks
            else:
                converted, row_count = decoder.decode(result.chunks, mode)
                contents[partition_id] = (converted,)
                row_counts[partition_id] = row_count
            start_cursor, end_cursor = result.cursor_start, result.cursor_end
            boundary = result.boundary
            adapter_labels.add(
                f"{adapter.source_type}@{getattr(adapter, 'adapter_version', 'unversioned')}"
            )
            for key, value in result.metadata:
                extra_metadata.append((f"fetch:{partition_id}:{key}", value))
            if result.next_cursor is not None:
                has_pages = True
                extra_metadata.append(
                    (f"next_cursor:{partition_id}", result.next_cursor)
                )

        if row_counts:
            version = DatasetVersion(
                dataset_id=version.dataset_id,
                version_id=version.version_id,
                created_at=version.created_at,
                data_layer=version.data_layer,
                partitions=tuple(
                    DataPartition(
                        partition_id=partition.partition_id,
                        partition_values=partition.partition_values,
                        event_time_start=partition.event_time_start,
                        event_time_end=partition.event_time_end,
                        record_count=row_counts.get(
                            partition.partition_id,
                            partition.record_count,
                        ),
                        content_reference=partition.content_reference,
                    )
                    for partition in version.partitions
                ),
                event_time_start=version.event_time_start,
                event_time_end=version.event_time_end,
                schema_id=version.schema_id,
                schema_version=version.schema_version,
                supersedes=version.supersedes,
            )

        reference = self._publisher.publish_version(
            dataset,
            version,
            expected_head,
            contents,
        )
        metadata = (
            ("format_id", decoder.format_id if decoder is not None else "raw-bytes"),
            ("source_type", source.source_type),
        )
        if decoder is not None and hasattr(decoder, "resolved_encoding"):
            metadata += (
                ("csv_encoding", decoder.resolved_encoding),
                ("csv_delimiter", decoder.resolved_delimiter),
            )
        if row_counts:
            metadata += (("record_counts", json.dumps(row_counts, sort_keys=True)),)
        now = datetime.now(timezone.utc)
        metadata += (
            ("source_adapter", ",".join(sorted(adapter_labels))),
            ("boundary", str(boundary)),
            ("fetched_at", now.isoformat()),
        )
        for partition_id, pairs in spec_pairs:
            metadata += tuple(
                (f"spec:{partition_id}:{key}", encoded) for key, encoded in pairs
            )
        metadata += tuple(extra_metadata)
        record_cursor = mode is AcquisitionMode.INCREMENTAL or has_pages
        record = AcquisitionRecord(
            acquisition_id=acquisition_id or uuid.uuid4().hex,
            source_id=source_id,
            dataset_version=reference,
            mode=mode,
            acquired_at=now,
            cursor_start=start_cursor if record_cursor else None,
            cursor_end=end_cursor if record_cursor else None,
            boundary=boundary if record_cursor else None,
            metadata=metadata,
        )
        self._acquisitions.save(record)
        return reference
