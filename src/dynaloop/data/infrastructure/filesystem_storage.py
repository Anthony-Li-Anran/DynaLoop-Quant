"""Immutable local-file implementation of the Data content storage protocol."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from threading import RLock

from dynaloop.data.domain.errors import ContentIntegrityError
from dynaloop.data.domain.models import ContentReference
from dynaloop.data.interfaces.protocols import StagedContentHandle


_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_CHUNK_SIZE = 1024 * 1024


class LocalFileStorageBackend:
    """Store immutable SHA-256-addressed content beneath a configured root."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).expanduser().resolve()
        self._staging_root = self._root / ".staging"
        self._objects_root = self._root / "objects"
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._objects_root.mkdir(parents=True, exist_ok=True)
        self._require_within_root(self._staging_root)
        self._require_within_root(self._objects_root)
        self._staged: dict[StagedContentHandle, Path] = {}
        self._lock = RLock()

    @property
    def backend_id(self) -> str:
        """Return the stable identifier for this adapter's storage format."""
        return "dynaloop-local-file-sha256-v1"

    def write_staged(self, chunks: Iterable[bytes]) -> StagedContentHandle:
        """Write byte chunks to a private, attempt-scoped temporary file."""
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="stage-",
            suffix=".tmp",
            dir=self._staging_root,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise ContentIntegrityError(
                            "Staged content chunks must be bytes."
                        )
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

        with self._lock:
            handle = StagedContentHandle(uuid.uuid4().hex)
            self._staged[handle] = temporary_path
        return handle

    def validate_staged(self, handle: StagedContentHandle) -> ContentReference:
        """Hash a staged file and return its complete immutable content identity."""
        path = self._staged_path(handle)
        digest_hex, size = self._hash_file(path)
        return ContentReference(
            backend_id=self.backend_id,
            storage_key=digest_hex,
            hash_algorithm="sha256",
            content_hash=digest_hex,
            size_bytes=size,
        )

    def commit_staged(
        self,
        handle: StagedContentHandle,
        reference: ContentReference,
    ) -> None:
        """Atomically expose validated bytes without replacing existing content."""
        staged_path = self._staged_path(handle)
        self._validate_reference(reference)
        digest, size = self._hash_file(staged_path)
        if (
            digest != reference.content_hash
            or (
                reference.size_bytes is not None
                and size != reference.size_bytes
            )
        ):
            raise ContentIntegrityError(
                "Staged bytes do not match the supplied ContentReference."
            )

        destination = self._content_path(reference)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._require_within_root(destination.parent)
        if destination.is_symlink():
            raise ContentIntegrityError("Refusing to use a symlink as immutable content.")
        try:
            os.link(staged_path, destination)
        except FileExistsError:
            if destination.is_symlink() or not destination.is_file() or not self._files_equal(
                staged_path,
                destination,
            ):
                raise ContentIntegrityError(
                    "Refusing to replace different immutable content."
                )

    def read_content(self, reference: ContentReference) -> Iterable[bytes]:
        """Read only a committed content reference, verifying it before yielding."""
        path = self._content_path(reference)
        if not path.is_file() or path.is_symlink():
            raise ContentIntegrityError(
                f"Committed content {reference!r} is not available."
            )
        return self._iter_verified_content(path, reference)

    def content_exists(self, reference: ContentReference) -> bool:
        """Report whether a safe, regular committed content path exists."""
        path = self._content_path(reference)
        return path.is_file() and not path.is_symlink()

    def verify_content(self, reference: ContentReference) -> bool:
        """Verify the committed bytes against the SHA-256 reference."""
        path = self._content_path(reference)
        if not path.exists():
            return False
        if path.is_symlink() or not path.is_file():
            raise ContentIntegrityError("Committed content is not a regular file.")
        digest, size = self._hash_file(path)
        if digest != reference.content_hash or (
            reference.size_bytes is not None and size != reference.size_bytes
        ):
            raise ContentIntegrityError(
                f"Committed content {reference!r} failed integrity verification."
            )
        return True

    def remove_content(self, reference: ContentReference) -> int:
        """Delete one committed object and return the number of bytes freed.

        The caller is responsible for proving that no other version references
        this content; content-addressed objects may be shared across datasets.
        """
        path = self._content_path(reference)
        if not path.is_file() or path.is_symlink():
            return 0
        size = path.stat().st_size
        with self._lock:
            path.unlink(missing_ok=True)
        return size

    def discard_staged(self, handle: StagedContentHandle) -> None:
        """Remove only a staging file tracked as owned by this backend instance."""
        with self._lock:
            path = self._staged.pop(handle, None)
        if path is not None:
            path.unlink(missing_ok=True)

    def _staged_path(self, handle: StagedContentHandle) -> Path:
        with self._lock:
            path = self._staged.get(handle)
        if path is None:
            raise ContentIntegrityError(
                f"Staging handle {handle!r} is unknown or not owned by this backend."
            )
        if not path.is_file() or path.is_symlink():
            raise ContentIntegrityError(f"Staged content for {handle!r} is unavailable.")
        self._require_within_root(path)
        return path

    def _content_path(self, reference: ContentReference) -> Path:
        self._validate_reference(reference)
        path = self._objects_root / reference.storage_key[:2] / reference.storage_key[2:]
        self._require_within_root(path.parent)
        return path

    def _validate_reference(self, reference: ContentReference) -> None:
        if not isinstance(reference, ContentReference):
            raise ContentIntegrityError("reference must be a ContentReference.")
        if reference.backend_id != self.backend_id:
            raise ContentIntegrityError("ContentReference belongs to another backend.")
        if (
            reference.hash_algorithm != "sha256"
            or _DIGEST_PATTERN.fullmatch(reference.storage_key) is None
            or reference.storage_key != reference.content_hash
        ):
            raise ContentIntegrityError("ContentReference has an unsupported storage key.")

    def _require_within_root(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self._root)
        except ValueError as exc:
            raise ContentIntegrityError(
                "Resolved storage path escapes the configured root."
            ) from exc

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    @staticmethod
    def _files_equal(first: Path, second: Path) -> bool:
        with first.open("rb") as first_stream, second.open("rb") as second_stream:
            while True:
                first_chunk = first_stream.read(_CHUNK_SIZE)
                second_chunk = second_stream.read(_CHUNK_SIZE)
                if first_chunk != second_chunk:
                    return False
                if not first_chunk:
                    return True

    @staticmethod
    def _iter_verified_content(
        path: Path,
        reference: ContentReference,
    ) -> Iterator[bytes]:
        with path.open("rb") as stream:
            digest = hashlib.sha256()
            size = 0
            while chunk := stream.read(_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
            if digest.hexdigest() != reference.content_hash or (
                reference.size_bytes is not None and size != reference.size_bytes
            ):
                raise ContentIntegrityError(
                    f"Committed content {reference!r} failed integrity verification."
                )
            stream.seek(0)
            while chunk := stream.read(_CHUNK_SIZE):
                yield chunk
