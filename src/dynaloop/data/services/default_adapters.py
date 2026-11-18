"""Default registrations for the built-in, dependency-free adapters."""

from __future__ import annotations

from typing import Any

from dynaloop.data.services.acquisition import (
    CsvFormatAdapter,
    KlineJsonFormatAdapter,
    LocalFileAcquisitionAdapter,
)
from dynaloop.data.services.adapter_registry import AdapterRegistry


def _source_descriptor(adapter: LocalFileAcquisitionAdapter) -> dict[str, object]:
    return {
        "adapter_version": adapter.adapter_version,
        "source_type": adapter.source_type,
        "supported_modes": sorted(mode.value for mode in adapter.supported_modes),
        "capabilities": sorted(adapter.capabilities),
    }


def _format_descriptor(adapter: Any) -> dict[str, object]:
    return {
        "adapter_version": adapter.adapter_version,
        "format_id": adapter.format_id,
        "supported_modes": sorted(mode.value for mode in adapter.supported_modes),
    }


def build_default_registries(
    *,
    file_adapter: LocalFileAcquisitionAdapter | None = None,
) -> tuple[AdapterRegistry[Any], AdapterRegistry[Any]]:
    """Return independent catalogs containing the built-in local integrations."""
    sample_source = file_adapter or LocalFileAcquisitionAdapter()
    sources: AdapterRegistry[Any] = AdapterRegistry()
    sources.register(
        sample_source.source_type,
        (lambda: sample_source)
        if file_adapter is not None
        else LocalFileAcquisitionAdapter,
        descriptor=_source_descriptor(sample_source),
    )
    formats: AdapterRegistry[Any] = AdapterRegistry()
    for adapter_class in (CsvFormatAdapter, KlineJsonFormatAdapter):
        sample_format = adapter_class()
        formats.register(
            sample_format.format_id,
            adapter_class,
            descriptor=_format_descriptor(sample_format),
        )
    return sources, formats
