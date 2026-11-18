"""Runtime-configured data sources (HTTP APIs and local files).

A saved configuration becomes a registered source without any code changes,
restart, or plugin file. The core still sees only raw bytes, an opaque boundary
and lineage; transport, headers and credentials stay here.
"""

from __future__ import annotations

from dynaloop.infrastructure import JsonMappingStore

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from dynaloop.data.domain.errors import DataDefinitionError
from dynaloop.data.domain.models import (
    AcquisitionMode,
    FetchRequest,
    FetchResult,
)
from dynaloop.data.services.acquisition import LocalFileAcquisitionAdapter
from dynaloop.data.services.adapter_registry import AdapterRegistry

_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MASK = "***"
_SENSITIVE_NAME_HINTS = (
    "authorization",
    "token",
    "apikey",
    "api_key",
    "secret",
    "password",
    "credential",
    "accesskey",
    "x-api-key",
)


def _is_sensitive(name: str) -> bool:
    folded = "".join(character for character in name.casefold() if character.isalnum())
    return any(hint.replace("_", "") in folded or hint in folded for hint in _SENSITIVE_NAME_HINTS)


@dataclass(frozen=True, slots=True)
class ApiSourceConfig:
    """One user-supplied source: an HTTP endpoint or a local file path."""

    key: str
    name: str
    url: str
    method: str = "GET"
    query: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str | None = None
    credential_value: str | None = None
    credential_env: str | None = None
    credential_name: str = "Authorization"
    credential_in: str = "header"
    cursor_param: str = "cursor"
    timeout: float = 30.0
    kind: str = "api"

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not _KEY_PATTERN.fullmatch(self.key):
            raise DataDefinitionError(
                "Source key must be lowercase letters, digits, '-' or '_'."
            )
        if not isinstance(self.name, str) or not self.name.strip():
            raise DataDefinitionError("Source name must be non-empty.")
        if self.kind not in ("api", "local"):
            raise DataDefinitionError("Source kind must be 'api' or 'local'.")
        if self.kind == "api":
            parsed = urlparse(self.url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise DataDefinitionError("Source URL must be an absolute http(s) URL.")
        elif not isinstance(self.url, str) or not self.url.strip():
            raise DataDefinitionError("Local source path must be non-empty.")
        if self.method not in ("GET", "POST"):
            raise DataDefinitionError("Source method must be GET or POST.")
        if self.credential_in not in ("header", "query"):
            raise DataDefinitionError("credential_in must be 'header' or 'query'.")
        if not isinstance(self.timeout, (int, float)) or not 0 < float(self.timeout) <= 300:
            raise DataDefinitionError("timeout must be between 0 and 300 seconds.")
        for label, mapping in (("query", self.query), ("headers", self.headers)):
            if not isinstance(mapping, Mapping) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in mapping.items()
            ):
                raise DataDefinitionError(f"{label} must map strings to strings.")

    def to_dict(self) -> dict[str, Any]:
        """Persistable representation; contains no credential values."""
        return {
            "key": self.key,
            "name": self.name,
            "url": self.url,
            "method": self.method,
            "query": dict(self.query),
            "headers": dict(self.headers),
            "body": self.body,
            "credential_value": self.credential_value,
            "credential_env": self.credential_env,
            "credential_name": self.credential_name,
            "credential_in": self.credential_in,
            "cursor_param": self.cursor_param,
            "timeout": self.timeout,
            "kind": self.kind,
        }

    def public_dict(self) -> dict[str, Any]:
        """Catalog representation with secret-bearing header values masked."""
        payload = self.to_dict()
        payload["headers"] = {
            key: (_MASK if value and _is_sensitive(key) else value)
            for key, value in self.headers.items()
        }
        payload["credential_value"] = _MASK if self.credential_value else None
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ApiSourceConfig:
        return cls(
            key=str(payload.get("key", "")),
            name=str(payload.get("name", "")),
            url=str(payload.get("url", "")),
            method=str(payload.get("method", "GET")),
            query=dict(payload.get("query") or {}),
            headers=dict(payload.get("headers") or {}),
            body=payload.get("body"),
            credential_value=payload.get("credential_value"),
            credential_env=payload.get("credential_env"),
            credential_name=str(payload.get("credential_name", "Authorization")),
            credential_in=str(payload.get("credential_in", "header")),
            cursor_param=str(payload.get("cursor_param", "cursor")),
            timeout=float(payload.get("timeout", 30.0)),
            kind=str(payload.get("kind", "api")),
        )


class ApiSourceStore:
    """JSON-file CRUD for user-supplied API configurations."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._store = JsonMappingStore(path, error_type=DataDefinitionError, label='Stored API source configurations', recover_invalid=False)

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, dict[str, Any]]:
        return self._store.read()

    def list_all(self) -> tuple[ApiSourceConfig, ...]:
        return tuple(
            ApiSourceConfig.from_dict(value)
            for _, value in sorted(self._read().items())
        )

    def get(self, key: str) -> ApiSourceConfig | None:
        payload = self._read().get(key)
        return ApiSourceConfig.from_dict(payload) if payload is not None else None

    def save(self, config: ApiSourceConfig) -> None:
        with self._store.transaction() as entries:
            entries[config.key] = config.to_dict()

    def delete(self, key: str) -> bool:
        with self._store.transaction() as entries:
            if key not in entries:
                return False
            del entries[key]
        return True


class ConfiguredHttpAdapter:
    """SourceAdapter built entirely from one saved configuration."""

    adapter_version = "1.0"
    supported_modes = frozenset(
        (AcquisitionMode.BATCH, AcquisitionMode.INCREMENTAL, AcquisitionMode.POLLING)
    )
    capabilities = frozenset({"configured_http", "query_override", "env_credential"})

    def __init__(self, config: ApiSourceConfig) -> None:
        self._config = config
        self.source_type = config.key

    @property
    def config(self) -> ApiSourceConfig:
        return self._config

    def fetch(self, request: FetchRequest) -> FetchResult:
        params: dict[str, str] = dict(self._config.query)
        for key, value in request.spec.items():
            if value is None:
                continue
            params[key] = (
                value
                if isinstance(value, str)
                else json.dumps(value, sort_keys=True, ensure_ascii=False)
            )
        headers: dict[str, str] = dict(self._config.headers)
        if request.cursor and self._config.cursor_param:
            params[self._config.cursor_param] = request.cursor

        if self._config.credential_value or self._config.credential_env:
            if self._config.credential_value:
                secret = self._config.credential_value
            else:
                secret = os.environ.get(self._config.credential_env or "")
                if not secret:
                    raise DataDefinitionError(
                        f"Environment variable '{self._config.credential_env}' is not set "
                        f"for source '{self._config.key}'."
                    )
            if self._config.credential_in == "header":
                headers[self._config.credential_name] = secret
            else:
                params[self._config.credential_name] = secret

        url = self._config.url
        if params:
            url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
        body = self._config.body.encode("utf-8") if self._config.body else None
        http_request = Request(
            url,
            data=body,
            headers=headers,
            method=self._config.method,
        )
        try:
            with urlopen(http_request, timeout=self._config.timeout) as response:
                raw = response.read()
                status = getattr(response, "status", 200)
        except URLError as exc:
            raise DataDefinitionError(
                f"Request to source '{self._config.key}' failed: {exc}"
            ) from exc

        digest = hashlib.sha256(raw).hexdigest()[:16]
        metadata = (
            ("endpoint", self._config.url.split("?", 1)[0]),
            ("http_method", self._config.method),
            ("http_status", str(status)),
            ("response_bytes", str(len(raw))),
        )
        return FetchResult(
            chunks=(raw,),
            boundary=f"http:{status}:sha256:{digest}",
            cursor_start=request.cursor,
            cursor_end=request.cursor,
            metadata=metadata,
        )


class ConfiguredLocalAdapter:
    """SourceAdapter backed by one saved local path configuration."""

    adapter_version = "1.0"
    supported_modes = LocalFileAcquisitionAdapter.supported_modes
    capabilities = frozenset({"configured_local", "seekable", "replayable"})

    def __init__(self, config: ApiSourceConfig) -> None:
        self._config = config
        self.source_type = config.key

    @property
    def config(self) -> ApiSourceConfig:
        return self._config

    def fetch(self, request: FetchRequest) -> FetchResult:
        inner = FetchRequest(
            source_type="local_file",
            spec={"path": self._config.url},
            mode=request.mode,
            cursor=request.cursor,
        )
        result = LocalFileAcquisitionAdapter().fetch(inner)
        return FetchResult(
            chunks=result.chunks,
            boundary=result.boundary,
            cursor_start=result.cursor_start,
            cursor_end=result.cursor_end,
            next_cursor=result.next_cursor,
            metadata=result.metadata + (("source_key", self._config.key),),
        )


def merge_masked_headers(
    submitted: Mapping[str, str],
    existing: ApiSourceConfig | None,
) -> dict[str, str]:
    """Keep stored secret values when the edit form echoes a masked value."""
    if existing is None:
        return dict(submitted)
    return {
        key: (existing.headers.get(key, value) if value == _MASK else value)
        for key, value in submitted.items()
    }


def merge_masked_credential(
    submitted: str | None,
    existing: ApiSourceConfig | None,
) -> str | None:
    """Keep a stored secret when the edit form echoes the masked placeholder."""
    if submitted == _MASK and existing is not None:
        return existing.credential_value
    return submitted


def register_api_sources(
    registry: AdapterRegistry[Any],
    configs: tuple[ApiSourceConfig, ...],
) -> None:
    """Make saved configurations available immediately, replacing stale entries."""
    for config in configs:
        if config.key in registry.keys():
            registry.unregister(config.key)

        if config.kind == "local":
            adapter_type = ConfiguredLocalAdapter

            def factory(bound: ApiSourceConfig = config) -> ConfiguredLocalAdapter:
                return ConfiguredLocalAdapter(bound)

            descriptor = {
                "adapter_version": "1.0",
                "source_type": config.key,
                "kind": "configured_local",
                "path": config.url,
                "supported_modes": sorted(mode.value for mode in adapter_type.supported_modes),
                "capabilities": sorted(adapter_type.capabilities),
            }
        else:
            adapter_type = ConfiguredHttpAdapter

            def factory(bound: ApiSourceConfig = config) -> ConfiguredHttpAdapter:
                return ConfiguredHttpAdapter(bound)

            descriptor = {
                "adapter_version": "1.0",
                "source_type": config.key,
                "kind": "configured_http",
                "endpoint": config.url.split("?", 1)[0],
                "supported_modes": sorted(mode.value for mode in adapter_type.supported_modes),
                "capabilities": sorted(adapter_type.capabilities),
            }
        registry.register(config.key, factory, descriptor=descriptor)
