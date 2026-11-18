"""FastAPI adapters for the existing DynaLoop module facades."""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from dynaloop.research_engine import (
    CertificationCatalog, DecisionLedger, DecisionRecordError, ExecutionCatalog,
    ResearchCatalog, WalkforwardCatalog,
)
from dynaloop.alternative_data import (
    AkshareNewsProvider,
    NullNewsProvider,
    build_subjective_input,
)
from dynaloop.live_strategy import (
    ExperienceEvent,
    LiveStrategyLibrary,
    StructuredCandidateCollector,
)

from dynaloop.data import (
    AdapterRegistry,
    AcquisitionMode,
    CsvFormatAdapter,
    KlineJsonFormatAdapter,
    DataFacade,
    DataLayer,
    DataPartition,
    DataSource,
    Dataset,
    DatasetVersion,
    DatasetVersionReference,
    FetchRequest,
    ApiSourceConfig,
    ApiSourceStore,
    fetch_bar_records,
    list_backtest_sources,
    SourceCapabilityStore,
    probe_source,
    merge_masked_credential,
    merge_masked_headers,
    normalize_spec,
    register_api_sources,
)
from dynaloop.data.domain.errors import (
    DataDefinitionError,
    DataNotFoundError,
    DatasetIdentityConflictError,
    DatasetVersionIdentityConflictError,
    DatasetVersionPublishConflictError,
    QualityGateError,
)
from dynaloop.experiment_management import ExperimentManagementFacade
from dynaloop.experiment_management.domain.errors import (
    ExperimentDefinitionError,
    ExperimentManagementError,
    ExperimentNotFoundError,
)
from dynaloop.infrastructure import (
    ConfigurationError,
    get_resource_snapshot,
    get_runtime_info,
    load_settings,
)
from dynaloop.validation_backtesting_engine import (
    BacktestConfig,
    BacktestError,
    RunConfigError,
    RunConfigRecord,
    RunConfigStore,
    RunResultStore,
    StaticFeed,
    available_strategies,
    build_strategy,
    get_strategy_catalog,
    run_backtest,
    run_saved_config,
    utc_now,
)
from dynaloop.interaction.loop_store import LoopRunStore, LoopStoreError
from dynaloop.interaction.panes import (
    build_panes,
    default_view_config,
    normalise_view_config,
)
from dynaloop.orchestrator import (
    SYNTHETIC_SOURCE_METADATA,
    LoopConfig,
    LoopError,
    LoopOrchestrator,
    synthetic_demo_records,
)

# Format adapters whose published bytes are JSON-lines records. Consumers that
# need columns (preview, distributions) accept exactly these identities.
RECORD_FORMAT_IDS = frozenset(
    (CsvFormatAdapter.format_id, KlineJsonFormatAdapter.format_id)
)


class ViewConfigPayload(BaseModel):
    """Which optional panes are visible for one stored run (view only)."""

    visible_panes: list[str] = Field(default_factory=list)


class RuntimePayload(BaseModel):
    runtime: dict[str, Any]
    resources: dict[str, Any]


class SettingsPayload(BaseModel):
    log_level: str


class AdapterCatalogPayload(BaseModel):
    source_adapters: list[dict[str, Any]] = Field(default_factory=list)
    format_adapters: list[dict[str, Any]] = Field(default_factory=list)


class HealthPayload(BaseModel):
    status: str


class BacktestConfigPayload(BaseModel):
    """A saved backtest setup; execution semantics stay opaque to this layer."""

    config_id: str
    name: str
    dataset_id: str
    version_id: str
    symbol: str
    strategy_class: str
    start: str | None = None
    end: str | None = None
    initial_cash: float = 100_000.0
    strategy_kwargs: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunBacktestPayload(BaseModel):
    """Execute a saved setup; optional window overrides stay caller-supplied."""

    config_id: str
    start: str | None = None
    end: str | None = None


class QuickBacktestPayload(BaseModel):
    """Selection-first run: pick a Data source, one symbol and a window.

    ``start``/``end`` are the caller's data window AND the engine's run window;
    ``run_start``/``run_end`` optionally crop a narrower window from the same
    tape. Strategy logic stays a code object: config only names a class and
    its kwargs (qlib workflow YAML / ml4t Strategy convention).
    """

    source_key: str = "tencent_ashare"
    symbol: str
    start: str | None = None
    end: str | None = None
    run_start: str | None = None
    run_end: str | None = None
    frequency: str = "1d"
    adjust: str = "qfq"
    initial_cash: float = 100_000.0
    strategy_class: str = "BuyAndHold"
    strategy_kwargs: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None


class LoopRunPayload(BaseModel):
    """One complete six-stage closed-loop run; all free parameters are frozen.

    ``source_key`` selects a declared Data source for the frozen window;
    omitting it runs explicitly labeled synthetic demo bars, never pretending
    to be live market data.
    """

    source_key: str | None = None
    symbol: str = "TEST"
    start: str = "2024-01-01"
    end: str = "2024-02-10"
    frequency: str = "1d"
    adjust: str = "qfq"
    seed: int = 7
    rounds: int = 3
    group_size: int = 6
    generator: str = "template"
    features: list[str] | None = None
    windows: list[int] | None = None
    bias_magnitude: float = 0.0
    bias_mode: str = "additive"
    proxy_reps: int = 120
    proxy_block_size: int = 4
    statistical_reps: int = 120
    statistical_block_size: int = 5
    alpha: float = 0.1
    direction_strength: float = 0.25
    experiment_id: str = "dynaloop-loop"

    def to_config(self, **overrides: Any) -> LoopConfig:
        values = self.model_dump(include=set(LoopConfig.__dataclass_fields__), exclude_none=True)
        return LoopConfig(**{**values, **overrides})

    @model_validator(mode="after")
    def validate_configuration(self) -> "LoopRunPayload":
        self.to_config()
        return self


class CsvImportPayload(BaseModel):
    dataset_id: str
    version_id: str
    record_count: int
    acquisition_id: str
    encoding: str
    delimiter: str


class ApiSourcePayload(BaseModel):
    """A user-supplied API endpoint; saved on the server, never in lineage."""

    key: str
    name: str
    url: str
    kind: Literal["api", "local"] = "api"
    method: Literal["GET", "POST"] = "GET"
    query: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    credential_value: str | None = None
    credential_env: str | None = None
    credential_name: str = "Authorization"
    credential_in: Literal["header", "query"] = "header"
    cursor_param: str = "cursor"
    timeout: float = 30.0

    def to_config(self, *, existing: ApiSourceConfig | None = None) -> ApiSourceConfig:
        headers = merge_masked_headers(self.headers, existing)
        return ApiSourceConfig(
            key=self.key.strip(),
            name=self.name.strip(),
            url=self.url.strip(),
            method=self.method,
            query=self.query,
            headers=headers,
            body=self.body,
            credential_value=merge_masked_credential(self.credential_value, existing),
            credential_env=self.credential_env.strip() if self.credential_env else None,
            credential_name=self.credential_name,
            credential_in=self.credential_in,
            cursor_param=self.cursor_param,
            timeout=self.timeout,
            kind=self.kind,
        )


class SourceImportPayload(BaseModel):
    """A source-agnostic acquisition request; ``spec`` never carries secrets."""

    source_type: str
    spec: dict[str, Any] = Field(default_factory=dict)
    dataset_id: str
    dataset_name: str
    mode: Literal["batch", "incremental", "polling", "streaming"] = "batch"
    cursor: str | None = None
    format_id: str | None = None
    partition_id: str = "all"
    quality_policy: Literal["report_only", "gate_on_fail"]


class DatasetMetadataPayload(BaseModel):
    """Editable descriptive fields; dataset identity and versions stay fixed."""

    name: str | None = None
    description: str | None = None


class SourceImportResult(BaseModel):
    dataset_id: str
    version_id: str
    acquisition_id: str
    source_type: str
    format_id: str
    boundary: str | None = None
    cursor_start: str | None = None
    cursor_end: str | None = None
    record_count: int = 0


class CsvColumnSummaryPayload(BaseModel):
    name: str
    inferred_type: str
    observed_count: int
    missing_count: int
    minimum: float | str | None = None
    mean: float | None = None
    standard_deviation: float | None = None
    maximum: float | str | None = None
    distinct_count: int = 0
    top_values: list[tuple[str, int]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CsvPreviewPayload(BaseModel):
    row_count: int
    columns: list[CsvColumnSummaryPayload]
    preview_rows: list[list[str | None]]
    preview_truncated: bool
    missing_policy: str = "common"


class DistributionBinPayload(BaseModel):
    lower: float
    upper: float
    count: int


class CategoryCountPayload(BaseModel):
    value: str
    count: int


class ColumnDistributionPayload(BaseModel):
    column: str
    kind: str
    observed_count: int
    missing_count: int
    rule: str
    bins: list[DistributionBinPayload] = Field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    categories: list[CategoryCountPayload] = Field(default_factory=list)
    other_count: int = 0


MAX_CSV_UPLOAD_BYTES = 10 * 1024 * 1024
LOCAL_UPLOAD_SOURCE = DataSource(
    source_id="local-upload",
    name="Local file upload",
    source_type="local_file",
)


def create_app(
    *,
    data_facade: DataFacade[bytes] | None = None,
    experiment_facade: ExperimentManagementFacade | None = None,
    source_adapter_registry: AdapterRegistry[Any] | None = None,
    format_adapter_registry: AdapterRegistry[Any] | None = None,
) -> FastAPI:
    """Create the HTTP adapter; all domain access is delegated to facades."""
    app = FastAPI(
        title="DynaLoop Interaction API",
        version="0.1.0",
        description="HTTP views, CSV preview, and local CSV import for DynaLoop capabilities.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in os.environ.get(
                "DYNALOOP_INTERACTION_ORIGINS",
                "http://localhost:5173",
            ).split(",")
            if origin.strip()
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    state_directory = Path(
        os.environ.get("DYNALOOP_STATE_DIRECTORY", "~/.dynaloop")
    ).expanduser()
    research_catalog = ResearchCatalog(os.environ.get("DYNALOOP_RESEARCH_DIRECTORY", str(state_directory / "research")))
    evidence_root = os.environ.get(
        "DYNALOOP_EVIDENCE_DIRECTORY",
        str(Path(__file__).resolve().parents[3] / "experiments" / "factor_stream"),
    )
    certification_catalog = CertificationCatalog(evidence_root)
    execution_catalog = ExecutionCatalog(evidence_root)
    walkforward_catalog = WalkforwardCatalog(evidence_root)
    decision_ledger = DecisionLedger(state_directory / "decisions.json")
    live_strategy = LiveStrategyLibrary(state_directory / "live_strategy.json")

    @app.get("/api/research/runs")
    def research_runs():
        return research_catalog.list_runs()

    @app.get("/api/research/runs/{run_id}")
    def research_run(run_id: str):
        try:
            return research_catalog.detail(run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Research run not found")
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=f"Cannot read research artifact: {exc}")

    @app.get("/api/evidence/rounds")
    def evidence_rounds():
        return certification_catalog.list_rounds()

    @app.get("/api/evidence/rounds/{round_id}")
    def evidence_round(round_id: str):
        try:
            return certification_catalog.detail(round_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Certification round not found")
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=f"Cannot read certification artifact: {exc}")

    @app.get("/api/evidence/executions")
    def evidence_executions():
        return execution_catalog.list_demos()

    @app.get("/api/evidence/executions/{demo_id}")
    def evidence_execution(demo_id: str):
        try:
            return execution_catalog.detail(demo_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Execution demo not found")
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=f"Cannot read execution artifact: {exc}")

    @app.post("/api/subjective/inputs")
    def subjective_inputs(payload: dict[str, Any] | None = None):
        """Assemble the point-in-time context for subjective LLM analysis.

        Report-only. News is best-effort and opt-in via ``live_news=true``;
        a failed feed is reported as unavailable, never fabricated.
        """
        body = payload or {}
        decision_time = str(body.get("decision_time") or datetime.now(timezone.utc).date().isoformat())
        symbols = tuple(str(s) for s in body.get("symbols", []))[:20]
        live_news = bool(body.get("live_news", False))
        provider: Any = AkshareNewsProvider() if live_news else NullNewsProvider(
            "live news not requested"
        )
        # Decision-time retrieval from the living strategy library, guarded by
        # available_at. The query is the caller's market/theme context.
        query = str(body.get("strategy_query") or " ".join(symbols) or body.get("context") or "")
        live_strategies = live_strategy.retrieve(
            query=query, decision_time=decision_time, top_k=int(body.get("strategy_top_k") or 5)
        ) if query else []
        return build_subjective_input(
            decision_time=decision_time,
            symbols=symbols,
            news_provider=provider,
            sentiment_snapshot=body.get("sentiment_snapshot"),
            a_share_summary=body.get("a_share_summary"),
            live_strategies=live_strategies,
        )

    @app.get("/api/subjective/llm-config")
    def subjective_llm_config():
        """Public cloud config for the keyless WorkBuddy LLM SDK.

        endpoint/publishableKey are public, Origin-bound values safe to ship to
        the browser. No secret or long-lived key is ever returned.
        """
        return {
            "enabled": True,
            "endpoint": os.environ.get(
                "DYNALOOP_LLM_ENDPOINT", "https://dynaloop-subjective.app.workbuddy.host"
            ),
            "publishableKey": os.environ.get(
                "DYNALOOP_LLM_PUBLISHABLE_KEY",
                "wbpk_Zq5nt6cjMg2e619ofnUfVm_PO57w0xS1dIGnyHpOOncx1dmeI38hrhW",
            ),
            "note": "Subjective analysis only; output is not a factor, verdict, or investment advice.",
        }

    @app.get("/api/strategy-library")
    def strategy_library_snapshot():
        """Read-only living-strategy library with report-only experience stars."""
        as_of = datetime.now(timezone.utc).date().isoformat()
        return jsonable_encoder(live_strategy.snapshot(as_of=as_of))

    @app.post("/api/strategy-library/refresh")
    def strategy_library_refresh(payload: dict[str, Any]):
        """Harvest structured candidates supplied by the daily automation.

        The automation performs the web search and schema-guided extraction;
        this endpoint only validates/normalises and stores. No network call is
        made here. Failures are reported as unavailable, never fabricated.
        """
        body = payload or {}
        candidates = body.get("candidates") or []
        if not isinstance(candidates, list):
            raise HTTPException(status_code=422, detail="candidates must be a list")
        collected_at = str(body.get("collected_at") or datetime.now(timezone.utc).date().isoformat())
        collector = StructuredCandidateCollector(
            candidates,
            collected_at=collected_at,
            extractor_version=body.get("extractor_version") or "schema-extract/1",
            prompt_version=body.get("prompt_version"),
        )
        return jsonable_encoder(live_strategy.refresh(
            collector, query=str(body.get("query") or ""), limit=int(body.get("limit") or 10)
        ))

    @app.post("/api/strategy-library/retrieve")
    def strategy_library_retrieve(payload: dict[str, Any]):
        """Point-in-time-safe strategies relevant to the current context."""
        body = payload or {}
        return jsonable_encoder(live_strategy.retrieve(
            query=str(body.get("query") or ""),
            decision_time=body.get("decision_time"),
            top_k=int(body.get("top_k") or 5),
        ))

    @app.post("/api/strategy-library/experience")
    def strategy_library_experience_record(payload: dict[str, Any]):
        """Attribute one simulated-execution outcome to referenced strategies."""
        body = payload or {}
        try:
            event = ExperienceEvent(
                event_id=str(body.get("event_id") or uuid.uuid4().hex),
                decision_id=str(body.get("decision_id") or ""),
                strategy_ids=tuple(str(s) for s in body.get("strategy_ids", [])),
                outcome=str(body.get("outcome") or ""),
                recorded_at=str(body.get("recorded_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
                decision_time=body.get("decision_time"),
                symbol=body.get("symbol"),
                realized_return=body.get("realized_return"),
                note=body.get("note"),
                meta=dict(body.get("meta") or {}),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"fingerprint": live_strategy.record_experience(event)}

    @app.get("/api/decisions")
    def decisions_list():
        return decision_ledger.list()

    @app.post("/api/decisions")
    def decisions_record(payload: dict[str, Any]):
        try:
            return decision_ledger.record(
                choice=payload.get("choice"),
                rationale=payload.get("rationale", ""),
                subjective_fingerprint=payload.get("subjective_fingerprint"),
                quantitative_fingerprint=payload.get("quantitative_fingerprint"),
                decision_time=payload.get("decision_time"),
            )
        except DecisionRecordError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.get("/api/evidence/walkforward")
    def evidence_walkforward():
        return walkforward_catalog.list_rounds()

    @app.get("/api/evidence/walkforward/{directory}")
    def evidence_walkforward_detail(directory: str):
        try:
            return walkforward_catalog.detail(directory)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Walk-forward diagnostic not found")
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=f"Cannot read walk-forward artifact: {exc}")

    app.state.data_facade = data_facade or DataFacade.open_local(
        os.environ.get("DYNALOOP_DATA_DATABASE", str(state_directory / "data.sqlite3")),
        os.environ.get("DYNALOOP_STORAGE_ROOT", str(state_directory / "objects")),
    )
    app.state.experiment_facade = experiment_facade or (
        ExperimentManagementFacade.open_local(
            os.environ.get(
                "DYNALOOP_EXPERIMENT_DATABASE",
                str(state_directory / "experiments.sqlite3"),
            )
        )
    )
    built_sources, built_formats = app.state.data_facade.adapter_registries()
    app.state.source_adapter_registry = source_adapter_registry or built_sources
    app.state.format_adapter_registry = format_adapter_registry or built_formats
    if source_adapter_registry is not None or format_adapter_registry is not None:
        app.state.data_facade.configure_adapters(
            app.state.source_adapter_registry,
            app.state.format_adapter_registry,
        )
    app.state.api_source_store = ApiSourceStore(
        os.environ.get(
            "DYNALOOP_API_SOURCES_PATH",
            str(state_directory / "api_sources.json"),
        )
    )
    app.state.source_capability_store = SourceCapabilityStore(
        app.state.api_source_store.path.parent / "source_capabilities.json"
    )
    register_api_sources(
        app.state.source_adapter_registry,
        app.state.api_source_store.list_all(),
    )
    app.state.run_config_store = RunConfigStore(
        os.environ.get(
            "DYNALOOP_BACKTEST_CONFIGS_PATH",
            str(state_directory / "backtest_configs.json"),
        )
    )
    app.state.run_result_store = RunResultStore(
        os.environ.get(
            "DYNALOOP_BACKTEST_RESULTS_PATH",
            str(state_directory / "backtest_results.json"),
        )
    )
    app.state.loop_run_store = LoopRunStore(
        os.environ.get(
            "DYNALOOP_LOOP_RUNS_PATH",
            str(state_directory / "loop_runs.json"),
        )
    )

    @app.exception_handler(RunConfigError)
    @app.exception_handler(BacktestError)
    @app.exception_handler(LoopError)
    @app.exception_handler(LoopStoreError)
    async def run_config_error_handler(_, exc: Exception):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(DataNotFoundError)
    @app.exception_handler(ExperimentNotFoundError)
    async def not_found_handler(_, exc: Exception):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DataDefinitionError)
    @app.exception_handler(ExperimentDefinitionError)
    async def invalid_request_handler(_, exc: Exception):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ExperimentManagementError)
    async def experiment_error_handler(_, exc: Exception):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(DatasetIdentityConflictError)
    @app.exception_handler(DatasetVersionIdentityConflictError)
    @app.exception_handler(DatasetVersionPublishConflictError)
    @app.exception_handler(QualityGateError)
    async def data_conflict_handler(
        _,
        exc: (
            DatasetIdentityConflictError
            | DatasetVersionIdentityConflictError
            | DatasetVersionPublishConflictError
            | QualityGateError
        ),
    ):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/api/health", response_model=HealthPayload)
    def health() -> HealthPayload:
        return HealthPayload(status="ok")

    @app.get("/api/runtime", response_model=RuntimePayload)
    def runtime() -> RuntimePayload:
        return RuntimePayload(
            runtime=jsonable_encoder(get_runtime_info()),
            resources=jsonable_encoder(get_resource_snapshot()),
        )

    @app.get("/api/settings", response_model=SettingsPayload)
    def settings() -> SettingsPayload:
        try:
            config_path = os.environ.get("DYNALOOP_CONFIG_PATH")
            configured = load_settings(config_path) if config_path else load_settings()
        except ConfigurationError as exc:
            return JSONResponse(status_code=500, content={"detail": str(exc)})
        return SettingsPayload(log_level=configured.log_level)

    @app.get("/api/data/adapters", response_model=AdapterCatalogPayload)
    def adapter_catalog() -> AdapterCatalogPayload:
        """List registered source and format adapters without instantiating them."""
        return AdapterCatalogPayload(
            source_adapters=list(app.state.source_adapter_registry.descriptors()),
            format_adapters=list(app.state.format_adapter_registry.descriptors()),
        )

    def persist_source(
        payload: ApiSourcePayload, *, key_override: str | None = None
    ) -> dict[str, Any]:
        """Create or update one saved source and register it immediately."""
        if key_override is not None:
            payload.key = key_override
        store: ApiSourceStore = app.state.api_source_store
        formats = app.state.format_adapter_registry
        key = payload.key.strip()
        if key in ("local_file", "csv") or key in formats.keys():
            raise HTTPException(
                status_code=422,
                detail=f"Source key '{key}' is reserved by a built-in adapter.",
            )
        existing = store.get(key)
        if key_override is not None and existing is None:
            raise HTTPException(status_code=404, detail=f"Source '{key}' is not saved.")
        try:
            config = payload.to_config(existing=existing)
        except DataDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.save(config)
        register_api_sources(app.state.source_adapter_registry, (config,))
        # Registration immediately probes the source, so it is backtest-ready
        # without any per-source adapter code or a restart.
        app.state.source_capability_store.save(config.key, probe_source(config))
        return config.public_dict()

    @app.get("/api/data/api-sources", response_model=list[dict[str, Any]])
    def api_sources() -> list[dict[str, Any]]:
        """List saved source configurations with secret values masked."""
        return [config.public_dict() for config in app.state.api_source_store.list_all()]

    @app.post("/api/data/api-sources", response_model=dict[str, Any])
    def save_api_source(payload: ApiSourcePayload) -> dict[str, Any]:
        """Save a filled-in source; it becomes importable with no restart."""
        return persist_source(payload)

    @app.put("/api/data/api-sources/{key}", response_model=dict[str, Any])
    def update_api_source(key: str, payload: ApiSourcePayload) -> dict[str, Any]:
        """Edit an existing source while keeping its identity."""
        return persist_source(payload, key_override=key)

    @app.delete("/api/data/api-sources/{key}", response_model=dict[str, str])
    def delete_api_source(key: str) -> dict[str, str]:
        """Remove a saved API and unregister it from the live source catalog."""
        store: ApiSourceStore = app.state.api_source_store
        if not store.delete(key):
            raise HTTPException(status_code=404, detail=f"API source '{key}' is not saved.")
        app.state.source_adapter_registry.unregister(key)
        app.state.source_capability_store.delete(key)
        return {"status": "deleted", "key": key}

    @app.post("/api/data/api-sources/{key}/reprobe", response_model=dict[str, Any])
    def reprobe_api_source(key: str) -> dict[str, Any]:
        """Re-run capability discovery after an upstream API changed shape."""
        config = app.state.api_source_store.get(key)
        if config is None:
            raise HTTPException(status_code=404, detail=f"API source '{key}' is not saved.")
        capability = app.state.source_capability_store.save(key, probe_source(config))
        return {
            "key": key,
            "status": capability.get("status"),
            "error": capability.get("error"),
            "columns": capability.get("columns", []),
            "missing_columns": capability.get("missing_columns", []),
            "controllable": capability.get("controllable", []),
        }

    @app.get("/api/data/sources", response_model=list[dict[str, Any]])
    def data_sources() -> list[dict[str, Any]]:
        return jsonable_encoder(app.state.data_facade.list_data_sources())

    @app.get("/api/data/datasets", response_model=list[dict[str, Any]])
    def datasets() -> list[dict[str, Any]]:
        """Visible datasets; archived ones are omitted but never destroyed."""
        return jsonable_encoder(app.state.data_facade.visible_datasets())

    @app.get("/api/data/datasets/archived", response_model=list[dict[str, Any]])
    def archived_datasets() -> list[dict[str, Any]]:
        hidden = set(app.state.data_facade.hidden_dataset_ids())
        return jsonable_encoder(
            [
                dataset
                for dataset in app.state.data_facade.list_datasets()
                if dataset.dataset_id in hidden
            ]
        )

    @app.patch("/api/data/datasets/{dataset_id}", response_model=dict[str, Any])
    def update_dataset(dataset_id: str, payload: DatasetMetadataPayload) -> dict[str, Any]:
        updated = app.state.data_facade.update_dataset_metadata(
            dataset_id, name=payload.name, description=payload.description
        )
        return jsonable_encoder(updated)

    @app.delete("/api/data/datasets/{dataset_id}", response_model=dict[str, str])
    def hide_dataset(dataset_id: str) -> dict[str, str]:
        app.state.data_facade.hide_dataset(dataset_id)
        return {"status": "archived", "dataset_id": dataset_id}

    @app.post(
        "/api/data/datasets/{dataset_id}/restore", response_model=dict[str, str]
    )
    def restore_dataset(dataset_id: str) -> dict[str, str]:
        app.state.data_facade.restore_dataset(dataset_id)
        return {"status": "restored", "dataset_id": dataset_id}

    @app.delete(
        "/api/data/datasets/{dataset_id}/purge", response_model=dict[str, Any]
    )
    def purge_dataset(dataset_id: str) -> dict[str, Any]:
        """Irreversibly delete an archived dataset and its unreferenced bytes."""
        facade = app.state.data_facade
        facade.get_dataset(dataset_id)
        if dataset_id not in facade.hidden_dataset_ids():
            raise HTTPException(
                status_code=409,
                detail="Archive the dataset before deleting it permanently.",
            )
        result = facade.purge_dataset(dataset_id)
        return {
            "status": "purged",
            "dataset_id": result.dataset_id,
            "deleted_versions": result.deleted_versions,
            "deleted_objects": result.deleted_objects,
            "deleted_bytes": result.deleted_bytes,
            "deleted_metadata": result.deleted_metadata,
        }

    @app.get(
        "/api/data/datasets/{dataset_id}/versions/{version_id}/preview",
        response_model=CsvPreviewPayload,
    )
    def dataset_version_preview(
        dataset_id: str,
        version_id: str,
        partition_id: str = "all",
        missing_policy: Literal["common", "blank"] = "common",
    ) -> CsvPreviewPayload:
        dataset = app.state.data_facade.get_dataset(dataset_id)
        if dataset.format_id not in RECORD_FORMAT_IDS:
            raise HTTPException(
                status_code=415,
                detail="Column preview is available for tabular datasets only.",
            )
        reference = DatasetVersionReference(dataset_id, version_id)
        records = app.state.data_facade.query_json_lines(reference, partition_id)
        preview = CsvFormatAdapter(missing_policy=missing_policy).preview_records(records)
        return CsvPreviewPayload(
            row_count=preview.row_count,
            columns=[
                CsvColumnSummaryPayload(
                    name=column.name,
                    inferred_type=column.inferred_type,
                    observed_count=column.observed_count,
                    missing_count=column.missing_count,
                    minimum=column.minimum,
                    mean=column.mean,
                    standard_deviation=column.standard_deviation,
                    maximum=column.maximum,
                    distinct_count=column.distinct_count,
                    top_values=list(column.top_values),
                    notes=list(column.notes),
                )
                for column in preview.columns
            ],
            preview_rows=[list(row) for row in preview.preview_rows],
            preview_truncated=preview.preview_truncated,
            missing_policy=preview.missing_policy,
        )

    @app.get(
        "/api/data/datasets/{dataset_id}/versions/{version_id}/distribution",
        response_model=ColumnDistributionPayload,
    )
    def column_distribution(
        dataset_id: str,
        version_id: str,
        column: str,
        partition_id: str = "all",
    ) -> ColumnDistributionPayload:
        dataset = app.state.data_facade.get_dataset(dataset_id)
        if dataset.format_id not in RECORD_FORMAT_IDS:
            raise HTTPException(
                status_code=415,
                detail="Column distributions are available for tabular datasets only.",
            )
        reference = DatasetVersionReference(dataset_id, version_id)
        distribution = app.state.data_facade.get_column_distribution(
            reference, partition_id, column
        )
        return ColumnDistributionPayload(
            column=distribution.column,
            kind=distribution.kind,
            observed_count=distribution.observed_count,
            missing_count=distribution.missing_count,
            rule=distribution.rule,
            bins=[
                DistributionBinPayload(
                    lower=bin.lower, upper=bin.upper, count=bin.count
                )
                for bin in distribution.bins
            ],
            minimum=distribution.minimum,
            maximum=distribution.maximum,
            mean=distribution.mean,
            categories=[
                CategoryCountPayload(value=item.value, count=item.count)
                for item in distribution.categories
            ],
            other_count=distribution.other_count,
        )

    @app.post("/api/data/import/csv", response_model=CsvImportPayload)
    async def import_csv(
        dataset_id: str = Form(...),
        dataset_name: str = Form(...),
        file: UploadFile = File(...),
        encoding: str = Form("auto"),
        delimiter: str = Form("auto"),
        quality_policy: str = Form(...),
    ) -> CsvImportPayload:
        if quality_policy not in ("report_only", "gate_on_fail"):
            raise HTTPException(
                status_code=422,
                detail="quality_policy must be 'report_only' or 'gate_on_fail'.",
            )
        try:
            content = await file.read(MAX_CSV_UPLOAD_BYTES + 1)
        finally:
            await file.close()
        if len(content) > MAX_CSV_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"CSV uploads must not exceed {MAX_CSV_UPLOAD_BYTES // (1024 * 1024)} MiB.",
            )

        csv_adapter = CsvFormatAdapter(encoding=encoding, delimiter=delimiter)
        _, record_count = csv_adapter.convert((content,), mode=AcquisitionMode.BATCH)
        source = LOCAL_UPLOAD_SOURCE
        requested_dataset = Dataset(
            dataset_id=dataset_id,
            name=dataset_name,
            source_ids=(source.source_id,),
            data_type="table",
            format_id=csv_adapter.format_id,
        )

        data_facade = app.state.data_facade
        dataset = next(
            (
                item
                for item in data_facade.list_datasets()
                if item.dataset_id == requested_dataset.dataset_id
            ),
            None,
        )
        if dataset is not None and (
            dataset.name != requested_dataset.name
            or source.source_id not in dataset.source_ids
            or dataset.format_id != csv_adapter.format_id
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Dataset ID '{dataset_id}' already exists with a different name, "
                    "source, or format."
                ),
            )

        registered_source = next(
            (
                item
                for item in data_facade.list_data_sources()
                if item.source_id == source.source_id
            ),
            None,
        )
        if registered_source is None:
            data_facade.register_data_source(source)
        elif registered_source != source:
            raise HTTPException(
                status_code=409,
                detail=f"Data source ID '{source.source_id}' is already used by another source.",
            )

        if dataset is None:
            dataset = requested_dataset
            data_facade.register_dataset(dataset)

        expected_head = data_facade.get_dataset_head(dataset.dataset_id)
        version_id = f"v-{uuid.uuid4().hex}"
        acquisition_id = uuid.uuid4().hex
        version = DatasetVersion(
            dataset_id=dataset.dataset_id,
            version_id=version_id,
            created_at=datetime.now(timezone.utc),
            data_layer=DataLayer.RAW,
            partitions=(DataPartition("all", record_count=record_count),),
            supersedes=expected_head,
        )
        with tempfile.TemporaryDirectory(prefix="dynaloop-csv-upload-") as directory:
            csv_path = Path(directory) / "upload.csv"
            csv_path.write_bytes(content)
            reference = data_facade.import_files(
                source.source_id,
                dataset,
                version,
                expected_head,
                {"all": csv_path},
                csv_adapter=csv_adapter,
                acquisition_id=acquisition_id,
                quality_policy=quality_policy,
            )
        return CsvImportPayload(
            dataset_id=reference.dataset_id,
            version_id=reference.version_id,
            record_count=record_count,
            acquisition_id=acquisition_id,
            encoding=csv_adapter.resolved_encoding,
            delimiter=csv_adapter.resolved_delimiter,
        )

    @app.post("/api/data/import/source", response_model=SourceImportResult)
    def import_source(payload: SourceImportPayload) -> SourceImportResult:
        """Fetch bytes from any registered source adapter and publish a version."""
        sources = app.state.source_adapter_registry
        formats = app.state.format_adapter_registry
        if payload.source_type not in sources.keys():
            raise HTTPException(
                status_code=422,
                detail=f"Source adapter '{payload.source_type}' is not registered.",
            )
        if payload.format_id and payload.format_id not in formats.keys():
            raise HTTPException(
                status_code=422,
                detail=f"Format adapter '{payload.format_id}' is not registered.",
            )
        try:
            normalize_spec(payload.spec)
            request = FetchRequest(
                source_type=payload.source_type,
                spec=payload.spec,
                mode=AcquisitionMode(payload.mode),
                cursor=payload.cursor,
            )
        except (DataDefinitionError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        data_facade = app.state.data_facade
        stored_source = app.state.api_source_store.get(payload.source_type)
        source_kind = stored_source.kind if stored_source is not None else "api"
        prefix = "local" if source_kind == "local" else "api"
        source = DataSource(
            source_id=f"{prefix}-{payload.source_type}",
            name=(
                f"{payload.source_type} local file source"
                if source_kind == "local"
                else f"{payload.source_type} API source"
            ),
            source_type=payload.source_type,
        )
        format_id = payload.format_id or "raw-bytes"
        requested = Dataset(
            dataset_id=payload.dataset_id,
            name=payload.dataset_name,
            source_ids=(source.source_id,),
            data_type="table",
            format_id=format_id,
        )
        existing = next(
            (
                item
                for item in data_facade.visible_datasets()
                if item.dataset_id == requested.dataset_id
            ),
            None,
        )
        archived_reuse = requested.dataset_id in set(
            data_facade.hidden_dataset_ids()
        )
        if existing is not None and (
            existing.name != requested.name
            or source.source_id not in existing.source_ids
            or existing.format_id != requested.format_id
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Dataset ID '{payload.dataset_id}' already exists with a "
                    "different name, source, or format."
                ),
            )
        registered_source = next(
            (
                item
                for item in data_facade.list_data_sources()
                if item.source_id == source.source_id
            ),
            None,
        )
        if registered_source is None:
            data_facade.register_data_source(source)
        elif registered_source != source:
            raise HTTPException(
                status_code=409,
                detail=f"Data source ID '{source.source_id}' is already used by another source.",
            )
        dataset = existing or requested
        created_new = existing is None and not archived_reuse
        if existing is None and archived_reuse:
            # An archived ID is available again. Replace its descriptive
            # definition (name/source/format) and clear the hidden flag;
            # published versions and content objects stay untouched.
            data_facade.replace_dataset_definition(requested)
            data_facade.restore_dataset(requested.dataset_id)
        elif existing is None:
            data_facade.register_dataset(dataset)

        expected_head = data_facade.get_dataset_head(dataset.dataset_id)
        acquisition_id = uuid.uuid4().hex
        version = DatasetVersion(
            dataset_id=dataset.dataset_id,
            version_id=f"v-{uuid.uuid4().hex}",
            created_at=datetime.now(timezone.utc),
            data_layer=DataLayer.RAW,
            partitions=(DataPartition(payload.partition_id),),
            supersedes=expected_head,
        )
        try:
            reference = data_facade.import_source(
                source.source_id,
                dataset,
                version,
                expected_head,
                {payload.partition_id: request},
                format_id=payload.format_id or None,
                acquisition_id=acquisition_id,
                quality_policy=payload.quality_policy,
            )
        except DataDefinitionError as exc:
            # A failed fetch must not leave a version-less dataset in the tree.
            # Only a definition created by this request is removed; an archived
            # ID reused here is simply archived again, keeping its old versions.
            if created_new:
                data_facade.hide_dataset(dataset.dataset_id)
                try:
                    data_facade.purge_dataset(dataset.dataset_id)
                except (DataDefinitionError, DataNotFoundError):
                    # Read-only facades cannot purge; hiding is still correct.
                    pass
            elif archived_reuse:
                data_facade.hide_dataset(dataset.dataset_id)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record = data_facade.get_acquisition(acquisition_id)
        lineage = dict(record.metadata)
        published = data_facade.get_dataset_version(reference)
        stored_count = next(
            (
                partition.record_count
                for partition in published.partitions
                if partition.partition_id == payload.partition_id
            ),
            None,
        )
        return SourceImportResult(
            dataset_id=reference.dataset_id,
            version_id=reference.version_id,
            acquisition_id=acquisition_id,
            source_type=payload.source_type,
            format_id=format_id,
            boundary=lineage.get("boundary") or record.boundary,
            cursor_start=record.cursor_start,
            cursor_end=record.cursor_end,
            record_count=stored_count or 0,
        )

    @app.get("/api/data/datasets/{dataset_id}", response_model=dict[str, Any])
    def dataset(dataset_id: str) -> dict[str, Any]:
        return jsonable_encoder(app.state.data_facade.get_dataset(dataset_id))

    @app.get(
        "/api/data/datasets/{dataset_id}/versions",
        response_model=list[dict[str, Any]],
    )
    def dataset_versions(dataset_id: str) -> list[dict[str, Any]]:
        return jsonable_encoder(app.state.data_facade.list_dataset_versions(dataset_id))

    @app.get("/api/data/snapshots", response_model=list[dict[str, Any]])
    def snapshots() -> list[dict[str, Any]]:
        return jsonable_encoder(app.state.data_facade.list_snapshots())

    @app.get("/api/data/snapshots/{snapshot_id}", response_model=dict[str, Any])
    def snapshot(snapshot_id: str) -> dict[str, Any]:
        return jsonable_encoder(app.state.data_facade.get_snapshot(snapshot_id))

    @app.get("/api/data/lineages", response_model=list[dict[str, Any]])
    def lineages() -> list[dict[str, Any]]:
        return jsonable_encoder(app.state.data_facade.list_lineages())

    @app.get("/api/data/quality-reports", response_model=list[dict[str, Any]])
    def quality_reports() -> list[dict[str, Any]]:
        return jsonable_encoder(app.state.data_facade.list_quality_reports())

    @app.get("/api/backtests/configs", response_model=list[dict[str, Any]])
    def list_backtest_configs() -> list[dict[str, Any]]:
        store: RunConfigStore = app.state.run_config_store
        return [jsonable_encoder(record.to_dict()) for record in store.list_all()]

    @app.post("/api/backtests/configs", response_model=dict[str, Any])
    def create_backtest_config(payload: BacktestConfigPayload) -> dict[str, Any]:
        store: RunConfigStore = app.state.run_config_store
        record = RunConfigRecord(**payload.model_dump()).with_timestamp(utc_now())
        if store.get(record.config_id) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Config ID '{record.config_id}' already exists.",
            )
        store.save(record)
        return jsonable_encoder(record.to_dict())

    @app.get("/api/backtests/configs/{config_id}", response_model=dict[str, Any])
    def get_backtest_config(config_id: str) -> dict[str, Any]:
        record: RunConfigRecord | None = app.state.run_config_store.get(config_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"Config '{config_id}' not found."
            )
        return jsonable_encoder(record.to_dict())

    @app.put("/api/backtests/configs/{config_id}", response_model=dict[str, Any])
    def update_backtest_config(
        config_id: str, payload: BacktestConfigPayload
    ) -> dict[str, Any]:
        store: RunConfigStore = app.state.run_config_store
        existing = store.get(config_id)
        if existing is None:
            raise HTTPException(
                status_code=404, detail=f"Config '{config_id}' not found."
            )
        if payload.config_id != config_id:
            raise HTTPException(
                status_code=422, detail="Config ID in body must match the path."
            )
        record = RunConfigRecord(**payload.model_dump()).with_timestamp(
            existing.created_at
        )
        store.save(record)
        return jsonable_encoder(record.to_dict())

    @app.delete("/api/backtests/configs/{config_id}", response_model=dict[str, str])
    def delete_backtest_config(config_id: str) -> dict[str, str]:
        store: RunConfigStore = app.state.run_config_store
        if not store.delete(config_id):
            raise HTTPException(
                status_code=404, detail=f"Config '{config_id}' not found."
            )
        return {"status": "deleted", "config_id": config_id}

    def backtest_records_provider(dataset_id: str, version_id: str):
        """Caller-side adapter: Data JSON-lines -> plain record mappings.

        The engine never imports Data domain types; this translation belongs
        to the integration side.
        """
        facade = app.state.data_facade
        reference = DatasetVersionReference(dataset_id, version_id)
        version = facade.get_dataset_version(reference)
        partitions = tuple(
            partition.partition_id for partition in version.partitions
        ) or ("all",)
        rows: list[dict[str, Any]] = []
        for partition_id in partitions:
            rows.extend(
                dict(row)
                for row in facade.query_json_lines(reference, partition_id)
            )
        return rows

    @app.get("/api/backtests/strategies", response_model=list[str])
    def list_backtest_strategies() -> list[str]:
        return list(available_strategies())

    @app.post("/api/backtests/run", response_model=dict[str, Any])
    def run_backtest_endpoint(payload: RunBacktestPayload) -> dict[str, Any]:
        config_store: RunConfigStore = app.state.run_config_store
        record = config_store.get(payload.config_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Config '{payload.config_id}' not found.",
            )
        try:
            result = run_saved_config(
                record,
                backtest_records_provider,
                start=payload.start,
                end=payload.end,
            )
        except (DataNotFoundError, DataDefinitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        fingerprint = result.fingerprint()
        run_id = f"{record.config_id}-{fingerprint[:12]}"
        app.state.run_result_store.save(
            run_id,
            {"config_id": record.config_id, "result": result.to_dict()},
        )
        return {
            "run_id": run_id,
            "fingerprint": fingerprint,
            "result": result.to_dict(),
        }

    @app.get("/api/backtests/results", response_model=list[dict[str, Any]])
    def list_backtest_results() -> list[dict[str, Any]]:
        return jsonable_encoder(list(app.state.run_result_store.list_all()))

    @app.get("/api/backtests/results/{run_id}", response_model=dict[str, Any])
    def get_backtest_result(run_id: str) -> dict[str, Any]:
        entry = app.state.run_result_store.get(run_id)
        if entry is None:
            raise HTTPException(
                status_code=404, detail=f"Run '{run_id}' not found."
            )
        return jsonable_encoder(entry)

    @app.put("/api/backtests/results/{run_id}/view-config", response_model=dict[str, Any])
    def save_view_config(run_id: str, payload: ViewConfigPayload) -> dict[str, Any]:
        """Persist pane visibility for one run without re-running the engine."""
        entry = app.state.run_result_store.get(run_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
        setup = dict(entry.get("setup") or {})
        panes = list(setup.get("panes") or [])
        if not panes:
            raise HTTPException(
                status_code=422,
                detail="This run has no pane declarations. Re-run it from Setup.",
            )
        view_config = normalise_view_config(
            panes, {"visible_panes": payload.visible_panes}
        )
        setup["view_config"] = view_config
        app.state.run_result_store.update_setup(run_id, setup)
        return {"run_id": run_id, "view_config": view_config}

    def data_adapter_registries() -> tuple[Any, Any]:
        """Data owns its adapters; Interaction only hands them back to Data."""
        return (
            app.state.source_adapter_registry,
            app.state.format_adapter_registry,
        )

    @app.get("/api/backtests/sources", response_model=list[dict[str, Any]])
    def list_backtest_sources_endpoint() -> list[dict[str, Any]]:
        # Data module answers "which sources can serve bars", including the
        # symbol / frequency / adjustment catalogue. No adapter is touched here.
        return jsonable_encoder(
            list_backtest_sources(
                app.state.api_source_store,
                data_adapter_registries(),
                app.state.source_capability_store,
            )
        )

    @app.get("/api/backtests/strategy-catalog", response_model=list[dict[str, Any]])
    def list_strategy_catalog() -> list[dict[str, Any]]:
        return jsonable_encoder(list(get_strategy_catalog()))

    @app.post("/api/backtests/quick-run", response_model=dict[str, Any])
    def quick_run_backtest(payload: QuickBacktestPayload) -> dict[str, Any]:
        """Source-mode run: Data fetches/decodes, the engine only sees bars."""
        try:
            rows, source_metadata = fetch_bar_records(
                data_adapter_registries(),
                source_key=payload.source_key,
                symbol=payload.symbol,
                start=payload.start,
                end=payload.end,
                frequency=payload.frequency,
                adjust=payload.adjust,
                capability_store=app.state.source_capability_store,
                store=app.state.api_source_store,
            )
        except (DataNotFoundError, DataDefinitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        execution = dict(payload.execution)
        execution["initial_cash"] = float(payload.initial_cash)
        execution["metadata"] = {
            "source_key": payload.source_key,
            "symbol": payload.symbol,
            "strategy_class": payload.strategy_class,
            "strategy_kwargs": dict(payload.strategy_kwargs),
            "fetch_window": {"start": payload.start, "end": payload.end},
            **dict(execution.get("metadata") or {}),
        }

        # Intraday endpoints serve a recent window, so the run window follows
        # the bars actually returned rather than the historical fetch window.
        resolved = source_metadata.get("resolved_window") or {}
        recent = bool(source_metadata.get("recent_window"))
        default_start = resolved.get("start") if recent else payload.start
        default_end = resolved.get("end") if recent else payload.end

        try:
            config = BacktestConfig.from_dict(execution)
            strategy = build_strategy(payload.strategy_class, payload.strategy_kwargs)
            feed = StaticFeed.from_records(
                rows,
                symbol=payload.symbol.strip(),
                metadata=source_metadata,
            )
            result = run_backtest(
                feed,
                strategy,
                config,
                start=payload.run_start if payload.run_start is not None else default_start,
                end=payload.run_end if payload.run_end is not None else default_end,
            )
        except (BacktestError, DataDefinitionError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        result_dict = result.to_dict()
        # View data is a side channel, never part of the engine result. The raw
        # tape keeps columns the six-field Bar projection drops (e.g. amount),
        # and panes are descriptions built only from what the source declared.
        timestamps = [
            str(frame.get("timestamp") or "")
            for frame in (result_dict.get("bars") or [])
        ]
        panes = build_panes(
            rows, timestamps, list(source_metadata.get("columns") or [])
        )
        view_config = default_view_config(panes)
        setup = {
            **payload.model_dump(),
            "tape": [dict(row) for row in rows],
            "panes": panes,
            "view_config": view_config,
        }
        label = payload.label or f"{payload.symbol} · {payload.strategy_class}"
        fingerprint = result.fingerprint()
        run_id = f"quick-{fingerprint[:14]}"
        app.state.run_result_store.save(
            run_id,
            {
                "config_id": None,
                "label": label,
                "setup": setup,
                "result": result_dict,
            },
        )
        return {
            "run_id": run_id,
            "fingerprint": fingerprint,
            "label": label,
            "panes": panes,
            "view_config": view_config,
            "result": result_dict,
        }

    @app.get("/api/experiments", response_model=list[dict[str, Any]])
    def experiments() -> list[dict[str, Any]]:
        return jsonable_encoder(app.state.experiment_facade.list_experiments())

    @app.get("/api/experiments/{experiment_id}", response_model=dict[str, Any])
    def experiment(experiment_id: str) -> dict[str, Any]:
        return jsonable_encoder(
            app.state.experiment_facade.get_experiment(experiment_id)
        )

    @app.get(
        "/api/experiments/{experiment_id}/runs",
        response_model=list[dict[str, Any]],
    )
    def experiment_runs(experiment_id: str) -> list[dict[str, Any]]:
        return jsonable_encoder(
            app.state.experiment_facade.list_runs(experiment_id)
        )

    @app.get("/api/runs/{run_id}", response_model=dict[str, Any])
    def run(run_id: str) -> dict[str, Any]:
        return jsonable_encoder(app.state.experiment_facade.get_run(run_id))

    @app.get("/api/runs/{run_id}/result", response_model=dict[str, Any] | None)
    def run_result(run_id: str) -> dict[str, Any] | None:
        return jsonable_encoder(app.state.experiment_facade.get_result(run_id))

    @app.post("/api/loop/runs", response_model=dict[str, Any])
    def run_loop(payload: LoopRunPayload) -> dict[str, Any]:
        """Drive the six-stage loop over one frozen window and trace every round.

        Records come from a declared Data source when ``source_key`` is given;
        otherwise the run uses explicitly labeled synthetic demo bars.
        """
        if payload.source_key:
            try:
                rows, source_metadata = fetch_bar_records(
                    data_adapter_registries(),
                    source_key=payload.source_key,
                    symbol=payload.symbol,
                    start=payload.start,
                    end=payload.end,
                    frequency=payload.frequency,
                    adjust=payload.adjust,
                    capability_store=app.state.source_capability_store,
                    store=app.state.api_source_store,
                )
            except (DataNotFoundError, DataDefinitionError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            declared = list(source_metadata.get("columns") or [])
            features = tuple(
                payload.features
                or [c for c in ("open", "high", "low", "close", "volume") if c in declared]
            )
            if not features:
                raise HTTPException(
                    status_code=422,
                    detail="No usable feature columns declared by this source.",
                )
            origin = f"source:{payload.source_key}"
        else:
            rows = synthetic_demo_records()
            source_metadata = dict(SYNTHETIC_SOURCE_METADATA)
            features = tuple(payload.features or ("open", "high", "low", "close", "volume"))
            origin = "synthetic-demo"

        resolved = source_metadata.get("resolved_window") or {}
        recent = bool(source_metadata.get("recent_window"))
        try:
            config = payload.to_config(
                features=features,
                start=resolved.get("start", payload.start) if recent else payload.start,
                end=resolved.get("end", payload.end) if recent else payload.end,
            )
            orchestrator = LoopOrchestrator(
                config, experiment_facade=app.state.experiment_facade
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = orchestrator.run(rows, source_metadata=source_metadata)
        return jsonable_encoder(
            app.state.loop_run_store.save(result.to_dict(), origin=origin)
        )

    @app.get("/api/loop/runs", response_model=list[dict[str, Any]])
    def loop_runs() -> list[dict[str, Any]]:
        entries = []
        for entry in app.state.loop_run_store.list_all():
            entries.append(
                {
                    "fingerprint": entry["fingerprint"],
                    "origin": entry["origin"],
                    "created_at": entry["created_at"],
                    "round_count": entry["round_count"],
                    "final_reliability": entry["final_reliability"],
                    "run_ids": entry["run_ids"],
                    "experiment_id": entry["experiment_id"],
                }
            )
        return jsonable_encoder(entries)

    @app.get("/api/loop/runs/{fingerprint}", response_model=dict[str, Any])
    def loop_run(fingerprint: str) -> dict[str, Any]:
        entry = app.state.loop_run_store.get(fingerprint)
        if entry is None:
            raise HTTPException(status_code=404, detail="Loop run not found.")
        return jsonable_encoder(entry)

    return app


def __getattr__(name: str) -> Any:
    """Keep ``api:app`` compatible without opening databases on import.

    Prefer ``uvicorn dynaloop.interaction.api:create_app --factory`` for
    servers; importing the factory or payload types has no storage effects.
    """
    if name != "app":
        raise AttributeError(name)
    from threading import RLock

    # Import-time access is serialized by Python's import machinery. The
    # explicit lock also covers concurrent attribute access after import.
    lock = globals().setdefault("_app_lock", RLock())
    with lock:
        if "app" not in globals():
            globals()["app"] = create_app()
        return globals()["app"]
