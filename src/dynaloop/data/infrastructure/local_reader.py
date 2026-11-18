"""Local DataReader resolving published partitions to immutable content."""

from collections.abc import Iterable

from dynaloop.data.domain.errors import DataNotFoundError
from dynaloop.data.domain.models import DatasetVersionReference
from dynaloop.data.interfaces.protocols import (
    DatasetVersionRepository,
    StorageBackend,
)


class LocalDataReader:
    """Read opaque stored bytes for partitions in published dataset versions."""

    def __init__(
        self,
        versions: DatasetVersionRepository,
        storage: StorageBackend,
    ) -> None:
        self._versions = versions
        self._storage = storage

    def read_partition(
        self,
        reference: DatasetVersionReference,
        partition_id: str,
    ) -> Iterable[bytes]:
        """Return verified content chunks for one published partition."""
        version = self._versions.get(reference)
        if version is None:
            raise DataNotFoundError(
                f"Dataset version '{reference.dataset_id}@{reference.version_id}' "
                "was not found."
            )
        partition = next(
            (item for item in version.partitions if item.partition_id == partition_id),
            None,
        )
        if partition is None or partition.content_reference is None:
            raise DataNotFoundError(
                f"Partition '{partition_id}' was not found in "
                f"version '{reference.dataset_id}@{reference.version_id}'."
            )
        return self._storage.read_content(partition.content_reference)
