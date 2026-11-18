"""Irreversible dataset deletion for the local SQLite + filesystem backend."""

from __future__ import annotations

from dynaloop.data.interfaces.protocols import DatasetPurgeResult

from .filesystem_storage import LocalFileStorageBackend
from .sqlite_repository import SQLiteMetadataRepository


class SQLiteDatasetMaintenance:
    """Purge archived datasets without deleting content shared by other datasets.

    Metadata is removed atomically first. Only afterwards are content objects
    with zero surviving version references unlinked from disk, so a partially
    failed byte removal can never resurrect a half-deleted dataset definition.
    """

    def __init__(
        self,
        metadata: SQLiteMetadataRepository,
        storage: LocalFileStorageBackend,
    ) -> None:
        self._metadata = metadata
        self._storage = storage

    def purge(self, dataset_id: str) -> DatasetPurgeResult:
        orphans, deleted_versions, deleted_metadata = self._metadata.purge_dataset(
            dataset_id
        )
        deleted_objects = 0
        deleted_bytes = 0
        for reference in orphans:
            if reference.backend_id != self._storage.backend_id:
                continue
            existed = self._storage.content_exists(reference)
            freed = self._storage.remove_content(reference)
            if existed:
                deleted_objects += 1
                deleted_bytes += freed
        return DatasetPurgeResult(
            dataset_id=dataset_id,
            deleted_versions=deleted_versions,
            deleted_objects=deleted_objects,
            deleted_bytes=deleted_bytes,
            deleted_metadata=deleted_metadata,
        )
