"""Application-level coordination for immutable DatasetVersion publication."""

from collections.abc import Iterable, Mapping

from dynaloop.data.domain.models import (
    ContentReference,
    DataPartition,
    Dataset,
    DatasetVersion,
    DatasetVersionReference,
)
from dynaloop.data.domain.errors import (
    ContentIntegrityError,
    DataDefinitionError,
    DataNotFoundError,
    DatasetVersionPublishConflictError,
)
from dynaloop.data.interfaces.protocols import (
    DatasetRepository,
    DatasetVersionRepository,
    StorageBackend,
    StagedContentHandle,
)


class DatasetVersionPublishingService:
    """Coordinate content staging, validation, metadata, and Head publication.

    Dependencies are injected so the service remains independent of concrete
    storage and metadata implementations. Repository publication is the
    visibility boundary; the service must not expose a candidate before it.
    """

    def __init__(
        self,
        datasets: DatasetRepository,
        versions: DatasetVersionRepository,
        storage: StorageBackend,
    ) -> None:
        self._datasets = datasets
        self._versions = versions
        self._storage = storage

    def publish_version(
        self,
        dataset: Dataset,
        version: DatasetVersion,
        expected_head: DatasetVersionReference | None,
        partition_contents: Mapping[str, Iterable[bytes]],
    ) -> DatasetVersionReference:
        """Publish a complete version or propagate an explicit failure.

        ``partition_contents`` maps this version's partition IDs to byte
        chunks. The returned reference identifies a published version only.
        The caller owns retry/re-prepare after a Head conflict. A complete
        immutable version must be reconstructed with its committed content
        references before candidate metadata is saved. Content commit precedes
        candidate save and Head CAS; a failed metadata publication may leave
        unreferenced committed content, but must not expose the candidate.
        """
        if not isinstance(dataset, Dataset):
            raise DataDefinitionError("dataset must be a Dataset.")
        if not isinstance(version, DatasetVersion):
            raise DataDefinitionError("version must be a DatasetVersion.")
        if version.dataset_id != dataset.dataset_id:
            raise DataDefinitionError(
                "DatasetVersion and Dataset must have the same dataset_id."
            )
        registered_dataset = self._datasets.get(dataset.dataset_id)
        if registered_dataset is None:
            raise DataNotFoundError(
                f"Dataset '{dataset.dataset_id}' is not registered."
            )
        if registered_dataset != dataset:
            raise DataDefinitionError(
                f"Dataset '{dataset.dataset_id}' does not match its registered definition."
            )
        if expected_head is not None and (
            not isinstance(expected_head, DatasetVersionReference)
            or expected_head.dataset_id != version.dataset_id
        ):
            raise DataDefinitionError(
                "expected_head must be a reference for the candidate dataset or None."
            )
        if not isinstance(partition_contents, Mapping):
            raise DataDefinitionError("partition_contents must be a mapping.")

        partition_ids = tuple(partition.partition_id for partition in version.partitions)
        expected_partition_ids = set(partition_ids)
        provided_partition_ids = set(partition_contents)
        missing_partition_ids = expected_partition_ids - provided_partition_ids
        unexpected_partition_ids = provided_partition_ids - expected_partition_ids
        if missing_partition_ids or unexpected_partition_ids:
            raise DataDefinitionError(
                "partition_contents must match the candidate partition IDs exactly; "
                f"missing={sorted(missing_partition_ids, key=repr)!r}, "
                f"unexpected={sorted(unexpected_partition_ids, key=repr)!r}."
            )

        staged_handles: list[StagedContentHandle] = []
        staged: list[tuple[StagedContentHandle, ContentReference]] = []
        complete_version: DatasetVersion
        try:
            finalized_partitions: list[DataPartition] = []
            for partition in version.partitions:
                handle = self._storage.write_staged(
                    partition_contents[partition.partition_id]
                )
                staged_handles.append(handle)
                reference = self._storage.validate_staged(handle)
                if not isinstance(reference, ContentReference):
                    raise ContentIntegrityError(
                        "StorageBackend.validate_staged must return a ContentReference."
                    )
                if reference.backend_id != self._storage.backend_id:
                    raise ContentIntegrityError(
                        "Staged content reference belongs to a different storage backend."
                    )
                staged.append((handle, reference))
                finalized_partitions.append(
                    DataPartition(
                        partition_id=partition.partition_id,
                        partition_values=partition.partition_values,
                        event_time_start=partition.event_time_start,
                        event_time_end=partition.event_time_end,
                        record_count=partition.record_count,
                        content_reference=reference,
                    )
                )

            complete_version = DatasetVersion(
                dataset_id=version.dataset_id,
                version_id=version.version_id,
                created_at=version.created_at,
                data_layer=version.data_layer,
                partitions=tuple(finalized_partitions),
                event_time_start=version.event_time_start,
                event_time_end=version.event_time_end,
                schema_id=version.schema_id,
                schema_version=version.schema_version,
                supersedes=version.supersedes,
            )
            complete_version.validate_content(dataset)

            for handle, reference in staged:
                self._storage.commit_staged(handle, reference)
            for _, reference in staged:
                if not self._storage.verify_content(reference):
                    raise ContentIntegrityError(
                        f"Committed content {reference!r} is missing or invalid."
                    )
        except BaseException as publication_error:
            cleanup_errors = self._discard_staged_handles(tuple(staged_handles))
            if cleanup_errors:
                raise BaseExceptionGroup(
                    "Version preparation failed and staged-content cleanup also failed.",
                    [publication_error, *cleanup_errors],
                ) from publication_error
            raise

        cleanup_errors = self._discard_staged_handles(
            tuple(staged_handles)
        )
        if cleanup_errors:
            raise ExceptionGroup(
                "Staged-content cleanup failed; candidate metadata was not saved.",
                cleanup_errors,
            )

        self._versions.save_candidate(complete_version)
        if not self._versions.publish_candidate(
            complete_version.reference,
            expected_head,
        ):
            raise DatasetVersionPublishConflictError(
                f"Dataset Head for '{dataset.dataset_id}' no longer matches "
                f"expected_head {expected_head!r}."
            )
        return complete_version.reference

    def _discard_staged_handles(
        self,
        handles: tuple[StagedContentHandle, ...],
    ) -> list[Exception]:
        """Discard only handles acquired by this invocation, reporting all failures."""
        errors: list[Exception] = []
        for handle in handles:
            try:
                self._storage.discard_staged(handle)
            except Exception as exc:
                errors.append(exc)
        return errors
