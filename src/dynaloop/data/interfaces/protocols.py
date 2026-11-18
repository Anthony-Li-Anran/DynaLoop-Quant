"""Contracts for Data metadata access, content storage, and reading."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import NewType, Protocol, TypeVar, runtime_checkable

from dynaloop.data.domain.models import (
    AcquisitionMode,
    AcquisitionRecord,
    ContentReference,
    FetchRequest,
    FetchResult,
    Dataset,
    DatasetSchema,
    DataSource,
    DatasetSnapshot,
    DatasetVersion,
    DatasetVersionReference,
    ProcessingLineage,
    QualityReport,
)
RecordT_co = TypeVar("RecordT_co", covariant=True)
StagedContentHandle = NewType("StagedContentHandle", str)


@dataclass(frozen=True, slots=True)
class DatasetPurgeResult:
    """Outcome of an irreversible dataset deletion."""

    dataset_id: str
    deleted_versions: int = 0
    deleted_objects: int = 0
    deleted_bytes: int = 0
    deleted_metadata: int = 0


class DatasetMaintenance(Protocol):
    """Management-plane operations that outlive the read-only data view."""

    def purge(self, dataset_id: str) -> DatasetPurgeResult:
        """Permanently delete an archived dataset and its unreferenced bytes."""
        ...


class DatasetRepository(Protocol):
    """Read and register logical dataset definitions by stable identity."""

    def get(self, dataset_id: str) -> Dataset | None:
        """Return a dataset, or None when its identity is unknown."""
        ...

    def list_all(self) -> tuple[Dataset, ...]:
        """Return registered datasets in stable identity order."""
        ...

    def register(self, dataset: Dataset) -> None:
        """Register a new definition without silently replacing an existing ID.

        Implementations should treat an identical existing definition as
        idempotent and raise DatasetIdentityConflictError for a different
        definition with the same dataset ID.
        """
        ...

    def update(self, dataset: Dataset) -> None:
        """Replace descriptive metadata while keeping the stable identity."""
        ...

    def archive(self, dataset_id: str) -> None:
        """Hide a dataset from management views without deleting stored content."""
        ...

    def restore(self, dataset_id: str) -> None:
        """Make an archived dataset visible again."""
        ...

    def archived_ids(self) -> tuple[str, ...]:
        """Return the identifiers currently hidden from management views."""
        ...


class DataSourceRepository(Protocol):
    """Persist non-secret source identity and descriptive metadata."""

    def get(self, source_id: str) -> DataSource | None:
        """Return a registered source or None."""
        ...

    def list_all(self) -> tuple[DataSource, ...]:
        """Return registered sources in stable identity order."""
        ...

    def register(self, source: DataSource) -> None:
        """Register a source without replacing a different definition."""
        ...


class DatasetSchemaRepository(Protocol):
    """Persist independent, dataset-specific schema versions."""

    def get(self, schema_id: str, version: str) -> DatasetSchema | None:
        """Return a schema version or None."""
        ...

    def register(self, schema: DatasetSchema) -> None:
        """Register an immutable schema definition."""
        ...


class DatasetVersionRepository(Protocol):
    """Persist candidates and publish immutable versions with Head CAS."""

    def get(self, reference: DatasetVersionReference) -> DatasetVersion | None:
        """Return only a published version, or None when it is unavailable."""
        ...

    def list_for_dataset(
        self,
        dataset_id: str,
    ) -> tuple[DatasetVersion, ...]:
        """Return published versions for a dataset in creation order."""
        ...

    def get_head(self, dataset_id: str) -> DatasetVersionReference | None:
        """Return the currently published Head, or None before first publish."""
        ...

    def save_candidate(self, version: DatasetVersion) -> None:
        """Persist candidate metadata without making it visible to readers.

        The caller must pass a complete immutable version whose partitions
        already carry their ContentReferences. Implementations retain that
        definition unchanged; saving a candidate does not publish it.
        Raise DatasetVersionIdentityConflictError when the reference already
        belongs to a different candidate or published definition.
        """
        ...

    def publish_candidate(
        self,
        reference: DatasetVersionReference,
        expected_head: DatasetVersionReference | None,
    ) -> bool:
        """Atomically publish a saved candidate iff the current Head matches.

        Return False on a Head conflict. This operation changes metadata
        visibility only; it must publish the saved candidate definition as-is,
        atomically changing its reader visibility and the Dataset Head. Callers
        must complete all domain and content validation before invoking it.
        A non-None expected_head must refer to the same dataset as reference. Raise
        DatasetVersionCandidateNotFoundError when the candidate does not exist and
        DatasetVersionCandidateStateError when it is not a saved candidate.
        """

    def retract_version(
        self,
        reference: DatasetVersionReference,
        *,
        restore_head: DatasetVersionReference | None,
    ) -> bool:
        """Retract a published version and restore the Dataset Head.

        Use only for explicit operational reversals such as a failed quality
        gate. The version row is deleted (its committed content remains
        content-addressed and orphaned); the audit trail is the caller's
        quality report. When the Head points at the retracted version, set it
        back to restore_head, or remove the Head row when restore_head is None.
        restore_head must refer to the same dataset and already be published.
        Return False when the version is not published; raise
        DataDefinitionError on identity or restore_head validation failures.
        """
        ...


class SnapshotRepository(Protocol):
    """Read and save immutable snapshot manifests."""

    def get(self, snapshot_id: str) -> DatasetSnapshot | None:
        """Return a saved snapshot, or None when its ID is unknown."""
        ...

    def list_all(self) -> tuple[DatasetSnapshot, ...]:
        """Return saved snapshots in stable identity order."""
        ...

    def save(self, snapshot: DatasetSnapshot) -> None:
        """Save a validated snapshot without replacing a different definition.

        The caller must validate explicit members and ensure all referenced
        versions have already been published.
        """
        ...


class ProcessingLineageRepository(Protocol):
    """Persist immutable processing lineage records."""

    def get(self, lineage_id: str) -> ProcessingLineage | None:
        """Return a lineage record or None."""
        ...

    def list_all(self) -> tuple[ProcessingLineage, ...]:
        """Return lineage records in stable identity order."""
        ...

    def save(self, lineage: ProcessingLineage) -> None:
        """Save without replacing a different definition."""
        ...


class QualityReportRepository(Protocol):
    """Persist quality outcomes for immutable versions."""

    def get(self, report_id: str) -> QualityReport | None:
        """Return a quality report or None."""
        ...

    def list_all(self) -> tuple[QualityReport, ...]:
        """Return quality reports in check-time order."""
        ...

    def save(self, report: QualityReport) -> None:
        """Save without replacing a different definition."""
        ...


class AcquisitionRepository(Protocol):
    """Persist successful acquisition metadata."""

    def get(self, acquisition_id: str) -> AcquisitionRecord | None:
        """Return an acquisition record or None."""
        ...

    def save(self, record: AcquisitionRecord) -> None:
        """Save successful import metadata without replacing a different record."""
        ...


class StorageBackend(Protocol):
    """Write, verify, and read immutable content without managing metadata."""

    @property
    def backend_id(self) -> str:
        """Return the stable ID represented by ContentReference.backend_id."""
        ...

    def write_staged(self, chunks: Iterable[bytes]) -> StagedContentHandle:
        """Write content into staging and return a handle scoped to this attempt."""
        ...

    def validate_staged(
        self,
        handle: StagedContentHandle,
    ) -> ContentReference:
        """Verify staged bytes and return their backend-neutral content reference."""
        ...

    def commit_staged(
        self,
        handle: StagedContentHandle,
        reference: ContentReference,
    ) -> None:
        """Make validated content immutable and addressable by its reference.

        The backend must confirm that the reference matches this staged
        content and must not overwrite different content under that reference.
        This does not publish any DatasetVersion or update a Dataset Head.
        Raise ContentIntegrityError when staged bytes do not match reference.
        """
        ...

    def read_content(self, reference: ContentReference) -> Iterable[bytes]:
        """Read committed content; staging handles are not accepted here."""
        ...

    def content_exists(self, reference: ContentReference) -> bool:
        """Report whether committed content for this reference exists."""
        ...

    def verify_content(self, reference: ContentReference) -> bool:
        """Check committed bytes against the reference's integrity metadata.

        Raise ContentIntegrityError when present bytes fail verification;
        return False when no committed content exists.
        """
        ...

    def discard_staged(self, handle: StagedContentHandle) -> None:
        """Discard only staging owned by this attempt; never affect committed content.

        Handles are attempt-scoped. Discarding an unknown, already discarded,
        or committed handle must not remove content that another operation or
        published version may reference.
        """
        ...


class DataReader(Protocol[RecordT_co]):
    """Read logical partition records without exposing physical storage."""

    def read_partition(
        self,
        reference: DatasetVersionReference,
        partition_id: str,
    ) -> Iterable[RecordT_co]:
        """Return records or raise DataNotFoundError for an unknown partition."""
        ...


@runtime_checkable
class SourceAdapter(Protocol):
    """Fetch raw bytes from one source without leaking transport semantics.

    The core recognizes only bytes, opaque cursors, and lineage metadata.
    Authentication, pagination and response shape stay inside the adapter.
    """

    source_type: str
    adapter_version: str
    supported_modes: frozenset[AcquisitionMode]
    capabilities: frozenset[str]

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Return unparsed chunks and adapter-owned cursor/boundary values."""
        ...


@runtime_checkable
class FormatAdapter(Protocol):
    """Decode raw bytes into one canonical payload and its record count."""

    format_id: str
    supported_modes: frozenset[AcquisitionMode]

    def decode(
        self,
        chunks: Iterable[bytes],
        mode: AcquisitionMode,
    ) -> tuple[bytes, int]:
        """Return canonical bytes and the number of decoded records."""
        ...
