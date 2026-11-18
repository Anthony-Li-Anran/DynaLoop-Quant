"""Data application services."""

from dynaloop.data.services.acquisition_spec import (
    DEFAULT_SENSITIVE_KEYS,
    normalize_spec,
)
from dynaloop.data.services.api_source import (
    ApiSourceConfig,
    ApiSourceStore,
    ConfiguredHttpAdapter,
    merge_masked_credential,
    merge_masked_headers,
    register_api_sources,
)
from dynaloop.data.services.adapter_registry import (
    AdapterRegistration,
    AdapterRegistry,
)
from dynaloop.data.services.acquisition import (
    AcquisitionService,
    CsvFormatAdapter,
    KlineJsonFormatAdapter,
    LocalFileAcquisitionAdapter,
)
from dynaloop.data.services.processing import (
    ProcessingOutput,
    ProcessingService,
    StandardizationResult,
    align_records_by_time,
    standardize_records,
)
from dynaloop.data.services.source_capabilities import (
    SourceCapabilityStore,
    get_or_probe,
    probe_source,
    source_signature,
)
from dynaloop.data.services.default_adapters import build_default_registries
from dynaloop.data.services.market_data import (
    ASHARE_SYMBOLS,
    BUILTIN_MARKET_SOURCES,
    fetch_bar_records,
    list_backtest_sources,
    resolve_market_source,
)
from dynaloop.data.services.distribution import (
    CategoryCount,
    ColumnDistribution,
    DistributionBin,
    summarize_column_distribution,
)
from dynaloop.data.services.publishing import DatasetVersionPublishingService
from dynaloop.data.services.quality import (
    QualityChecker,
    QualityService,
    SchemaQualityChecker,
)

__all__ = [
    "ASHARE_SYMBOLS",
    "BUILTIN_MARKET_SOURCES",
    "DEFAULT_SENSITIVE_KEYS",
    "AdapterRegistration",
    "ApiSourceConfig",
    "ApiSourceStore",
    "ConfiguredHttpAdapter",
    "AdapterRegistry",
    "AcquisitionService",
    "CategoryCount",
    "ColumnDistribution",
    "CsvFormatAdapter",
    "KlineJsonFormatAdapter",
    "DatasetVersionPublishingService",
    "DistributionBin",
    "LocalFileAcquisitionAdapter",
    "ProcessingOutput",
    "ProcessingService",
    "QualityChecker",
    "QualityService",
    "SchemaQualityChecker",
    "StandardizationResult",
    "SourceCapabilityStore",
    "align_records_by_time",
    "build_default_registries",
    "get_or_probe",
    "probe_source",
    "source_signature",
    "fetch_bar_records",
    "list_backtest_sources",
    "resolve_market_source",
    "merge_masked_credential",
    "merge_masked_headers",
    "normalize_spec",
    "register_api_sources",
    "standardize_records",
    "summarize_column_distribution",
]
