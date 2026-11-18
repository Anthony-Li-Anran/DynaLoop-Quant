"""Atomic JSON mappings with process-safe read/modify/write transactions.

FileLock protects a separate lock file, so replacing the data file does not
invalidate the lock. Readers see complete snapshots; writers lock the entire
transaction, not just the final rename. Intended for local filesystems.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from filelock import FileLock


class JsonMappingStore:
    def __init__(self, path: str | Path, *, error_type: type[Exception] = ValueError,
                 label: str = "JSON store", recover_invalid: bool = False) -> None:
        self._path = Path(path)
        self._error_type = error_type
        self._label = label
        self._recover_invalid = recover_invalid

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or any(not isinstance(v, dict) for v in payload.values()):
                raise ValueError("Expected a mapping of objects.")
            return payload
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            if self._recover_invalid:
                return {}
            raise self._error_type(f"{self._label} is unreadable or invalid.") from error

    def _write(self, entries: Mapping[str, dict[str, Any]]) -> None:
        # Serialize before creating a file so invalid numbers cannot damage a snapshot.
        text = json.dumps(entries, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        descriptor, name = tempfile.mkstemp(prefix=self._path.name + ".", suffix=".tmp", dir=self._path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def transaction(self) -> Iterator[dict[str, dict[str, Any]]]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = str(self._path.resolve()) + ".lock"
        try:
            with FileLock(lock_path, timeout=30):
                entries = self.read()
                yield entries
                self._write(entries)
        except OSError as error:
            raise self._error_type(f"Cannot update {self._label}.") from error
