export interface Dataset {
  dataset_id: string;
  name: string;
  description?: string | null;
  source_ids: string[];
  data_type?: string | null;
  market?: string | null;
  time_granularity?: string | null;
  format_id?: string | null;
}

export interface DatasetVersion {
  dataset_id: string;
  version_id: string;
  created_at: string;
  data_layer: string;
  schema_id?: string | null;
  schema_version?: string | null;
  partitions: DataPartition[];
  event_time_start?: string | null;
  event_time_end?: string | null;
}

export interface DataPartition {
  partition_id: string;
  partition_values: [string, string][];
  record_count?: number | null;
  content_reference?: {
    backend_id: string;
    storage_key: string;
    hash_algorithm: string;
    content_hash: string;
    size_bytes: number | null;
  } | null;
}

export interface DatasetSnapshot {
  snapshot_id: string;
  members: { dataset_id: string; version_id: string }[];
  partition_sources: {
    dataset_id: string;
    partition_values: [string, string][];
    source_version: { dataset_id: string; version_id: string };
    partition_id: string;
  }[];
}

export interface ProcessingLineage {
  lineage_id: string;
  operation_name: string;
  operation_version: string;
  input_versions: { dataset_id: string; version_id: string }[];
  output_versions: { dataset_id: string; version_id: string }[];
  executed_at: string;
  parameters: [string, string | number | boolean | null][];
}

export interface QualityReport {
  report_id: string;
  dataset_version: { dataset_id: string; version_id: string };
  rule_set_id: string;
  rule_set_version: string;
  checked_at: string;
  status: "passed" | "warning" | "failed";
  findings: string[];
}

export interface Experiment {
  experiment_id: string;
  name: string;
  description?: string | null;
  research_purpose?: string | null;
  configuration_reference?: string | null;
  configuration_version?: string | null;
}

export interface ExperimentRun {
  run_id: string;
  experiment_id: string;
  configuration_snapshot: string;
  configuration_version?: string | null;
  created_at: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  started_at?: string | null;
  finished_at?: string | null;
  failure_message?: string | null;
}

export interface ExperimentResult {
  result_id: string;
  run_id: string;
  metrics: [string, number][];
  artifacts: { artifact_type: string; artifact_id: string; version: string }[];
}

export interface DataSource {
  source_id: string;
  name: string;
  source_type: string;
  description?: string | null;
}

export interface CsvImportResult {
  dataset_id: string;
  version_id: string;
  record_count: number;
  acquisition_id: string;
  encoding?: string;
  delimiter?: string;
}

export interface SourceImportResult {
  dataset_id: string;
  version_id: string;
  acquisition_id: string;
  source_type: string;
  format_id: string;
  boundary: string | null;
  cursor_start: string | null;
  cursor_end: string | null;
  record_count: number;
}

export type QualityPolicy = "report_only" | "gate_on_fail";

export interface CsvColumnSummary {
  distinct_count: number;
  top_values: [string, number][];
  notes: string[];
  name: string;
  inferred_type: "number" | "date" | "datetime" | "boolean" | "mixed" | "text" | "empty";
  observed_count: number;
  missing_count: number;
  minimum: number | string | null;
  mean: number | null;
  standard_deviation: number | null;
  maximum: number | string | null;
}

export interface CsvPreview {
  row_count: number;
  columns: CsvColumnSummary[];
  preview_rows: (string | null)[][];
  preview_truncated: boolean;
  missing_policy: "common" | "blank";
}

export interface DistributionBin {
  lower: number;
  upper: number;
  count: number;
}

export interface CategoryCount {
  value: string;
  count: number;
}

export interface ColumnDistribution {
  column: string;
  kind: "histogram" | "categories" | "empty";
  observed_count: number;
  missing_count: number;
  rule: string;
  bins: DistributionBin[];
  minimum: number | null;
  maximum: number | null;
  mean: number | null;
  categories: CategoryCount[];
  other_count: number;
}

export interface ApiSource {
  key: string;
  name: string;
  url: string;
  kind?: "api" | "local";
  method: "GET" | "POST";
  query: Record<string, string>;
  headers: Record<string, string>;
  body: string | null;
  credential_value: string | null;
  credential_env: string | null;
  credential_name: string;
  credential_in: "header" | "query";
  cursor_param: string;
  timeout: number;
}

export type ApiSourceInput = ApiSource;

export interface RuntimePayload {
  runtime: {
    python_version: string;
    python_executable: string | null;
    os_name: string | null;
    platform: string | null;
    project_version: string | null;
  };
  resources: {
    captured_at: string;
    cpu_logical_count: number | null;
    cpu_available_count: number | null;
    memory_total_bytes: number | null;
    memory_available_bytes: number | null;
    accelerators: null;
  };
}

export interface SettingsPayload {
  log_level: string;
}

export interface BacktestConfigRecord {
  config_id: string;
  name: string;
  dataset_id: string;
  version_id: string;
  symbol: string;
  strategy_class: string;
  start: string | null;
  end: string | null;
  initial_cash: number;
  strategy_kwargs: Record<string, unknown>;
  execution: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
}

export type BacktestConfigInput = Omit<BacktestConfigRecord, "created_at">;

export interface BacktestSource {
  key: string;
  name: string;
  kind: string;
  endpoint: string | null;
  registered: boolean;
  builtin: boolean;
  compatible: boolean;
  format_id: string | null;
  capability_status: string;
  capability_error: string | null;
  columns: string[];
  missing_columns: string[];
  extra_columns: string[];
  inferred_columns: string[];
  controllable: string[];
  frequencies: { value: string; label: string }[];
  adjustments: { value: string; label: string }[];
  symbols: { symbol: string; name: string; kind: string }[];
  default_start: string;
  default_end: string;
  description: string;
}

export interface StrategyParameter {
  key: string;
  label: string;
  type: "number" | "integer";
  default: number;
  min?: number;
  max?: number;
  step?: number;
}

export interface StrategyCatalogEntry {
  class: string;
  label: string;
  summary: string;
  custom: boolean;
  parameters: StrategyParameter[];
}

export interface QuickRunInput {
  source_key: string;
  symbol: string;
  start: string | null;
  end: string | null;
  run_start?: string | null;
  run_end?: string | null;
  frequency: string;
  adjust: string;
  initial_cash: number;
  strategy_class: string;
  strategy_kwargs: Record<string, unknown>;
  execution: Record<string, unknown>;
  label?: string;
}

export interface PaneSeries {
  label: string;
  style: "line" | "histogram" | "candle";
  values: (number | null)[];
}

export interface PaneSpec {
  id: string;
  label: string;
  unit: string;
  format: string;
  kind: "raw" | "indicator";
  placement: "overlay" | "separate";
  // Legacy runs stored these fields; new runs simply omit unavailable panes.
  available?: boolean;
  reason?: string | null;
  definition: string | null;
  warmup: number;
  reference_lines: number[];
  series: PaneSeries[];
}

export interface BacktestViewConfig {
  visible_panes: string[];
}

export interface ReplaySetupExtras {
  panes?: PaneSpec[];
  view_config?: BacktestViewConfig;
  tape?: Record<string, unknown>[];
}

export interface BacktestBar {
  timestamp: string;
  symbol: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface BacktestBarFrame {
  timestamp: string;
  bars: Record<string, BacktestBar>;
}

export interface BacktestFill {
  fill_id: string;
  order_id: string;
  bar_index: number;
  timestamp: string;
  symbol: string;
  quantity: number;
  price: number;
  commission: number;
  slippage: number;
  cash_delta: number;
  status: string;
  reason: string;
}

export interface BacktestPortfolioState {
  bar_index: number;
  timestamp: string;
  cash: number;
  equity: number;
  positions: Record<string, number>;
  marks: Record<string, number>;
}

export interface BacktestMetrics {
  initial_cash: number;
  final_equity: number;
  total_return: number;
  max_drawdown: number;
  turnover: number;
  bar_count: number;
  fill_count: number;
  rejected_count: number;
  final_positions: Record<string, number>;
  reconciliation_max_abs: number;
  annualized_volatility: number | null;
  sharpe_ratio: number | null;
}

export interface BacktestResult {
  resolved_config: Record<string, unknown>;
  spec: {
    realized_window: { start: string | null; end: string | null };
    bar_count: number;
    symbols: string[];
    library_versions: Record<string, string | null>;
    config_fingerprint: string;
    feed_metadata: Record<string, unknown>;
  };
  warnings: string[];
  orders: Record<string, unknown>[];
  fills: BacktestFill[];
  portfolio_state: BacktestPortfolioState[];
  bars: BacktestBarFrame[];
  metrics: BacktestMetrics;
  benchmark: {
    type: string;
    symbol: string;
    quantity: number;
    equity: number[];
    total_return: number;
    aligned_bar_count: number;
  } | null;
}

export interface BacktestRunResponse {
  run_id: string;
  fingerprint: string;
  label?: string | null;
  panes?: PaneSpec[];
  view_config?: BacktestViewConfig;
  result: BacktestResult;
}

export interface BacktestResultSummary {
  run_id: string;
  config_id: string | null;
  label?: string | null;
  source_key?: string | null;
  symbol?: string | null;
  strategy_class?: string | null;
  created_at: string | null;
  window: { start: string | null; end: string | null } | null;
  bar_count: number | null;
  final_equity: number | null;
  total_return: number | null;
  fill_count: number | null;
}

export interface BacktestResultDetail {
  run_id: string;
  config_id: string | null;
  label?: string | null;
  setup?: (Partial<QuickRunInput> & ReplaySetupExtras) | null;
  created_at: string | null;
  result: BacktestResult;
}

export interface EvidenceWindow {
  start: string | null;
  end: string | null;
}

export interface EvidenceRoundSummary {
  round_id: string;
  status: string;
  family_p_value: number | null;
  periods: number | null;
  candidate_count: number | null;
  effective_count: number | null;
  verification_window: EvidenceWindow | null;
  freeze_fingerprint: string | null;
  source_sha256: string | null;
  channel?: string | null;
  channel_label?: string | null;
}

export interface EvidenceCandidate {
  factor_id: string | null;
  expression: string | null;
  status: string | null;
  effective: boolean;
  adjusted_p_value: number | null;
  mean_rank_ic: number | null;
  mean_improvement: number | null;
  periods: number | null;
  reasons: string[];
}

export interface EvidenceRoundDetail extends EvidenceRoundSummary {
  assertion: string | null;
  family: {
    p_value: number | null;
    alpha: number | null;
    method: string | null;
    family_size: number | null;
    rejected_count: number | null;
    spec: Record<string, unknown>;
  };
  fingerprints: {
    freeze: string | null;
    report: string | null;
    model: string | null;
  };
  effective_factor_ids: string[];
  candidates: EvidenceCandidate[];
  descriptive_metrics: Record<string, unknown> | null;
  disclosure: {
    contamination: string | null;
    data_caveats: string[];
    not_claimed: string[];
    limitations: unknown;
  };
  source_file: string;
}

export interface ExecutionDemoSummary {
  demo_id: string;
  purpose: string;
  no_new_effectiveness_claim: boolean | null;
  full_fingerprint: string | null;
  backtest_window: [string, string] | null;
  source_sha256: string | null;
}

export interface ExecutionDemoDetail extends ExecutionDemoSummary {
  consumed_factor: Record<string, unknown>;
  data_provenance: Record<string, unknown>;
  selection_rule_fingerprint: string | null;
  timing_rule_fingerprint: string | null;
  timing_demo: {
    purpose: string | null;
    learn_window_end: string | null;
    verify_window: [string, string] | null;
    timing_symbol: string | null;
    n_learning_samples: number | null;
    n_verification_samples: number | null;
    n_candidates: number | null;
    frozen_rule: Record<string, unknown>;
  };
  backtest: {
    window: [string, string] | null;
    n_decision_dates: number | null;
    metrics: Record<string, unknown>;
    fingerprint: string | null;
  };
  replay: { identical: boolean | null; full_fingerprint: string | null };
  frozen_strategy: {
    timing: {
      entry_threshold: number | null;
      exit_threshold: number | null;
      selected_symbol_count: number | null;
      selection_rule_fingerprint: string | null;
      certification_fingerprint: string | null;
      is_fallback: boolean;
      round_id: string | null;
    };
    selection: {
      fingerprint: string | null;
      factor_ids: string[] | null;
      top_k: number | null;
      weight_config: Record<string, unknown> | null;
      verified: boolean;
    };
    risk: {
      initial_cash: number | null;
      final_equity: number | null;
      total_return: number | null;
      max_drawdown: number | null;
      turnover: number | null;
      bar_count: number | null;
      fill_count: number | null;
      rejected_count: number | null;
      final_position_count: number | null;
      sharpe_ratio: number | null;
      annualized_volatility: number | null;
      reconciliation_max_abs: number | null;
    };
    disclosure: {
      no_new_effectiveness_claim: boolean;
      n_candidates: number | null;
    };
  };
}

export interface WalkforwardSummary {
  round_id: string;
  directory: string;
  purpose: string | null;
  channel_label: string | null;
  fold_count: number | null;
  effective_folds: number[];
  refuted_folds: number[];
  insufficient_folds: number[];
  no_new_effectiveness_claim: boolean;
  no_pooled_p_value: boolean;
  freeze_fingerprint: string | null;
  source_sha256: string | null;
}

export interface WalkforwardDetail {
  round_id: string;
  directory: string;
  purpose: string | null;
  channel: string | null;
  channel_label: string | null;
  fold_count: number | null;
  folds: {
    fold: number | null;
    window: string[];
    periods: number | null;
    family_p_value: number | null;
    status: string | null;
    rank_ic: number | null;
    cutoff: string | null;
    fit_window: (string | null)[];
    test_window: (string | null)[];
    effective: boolean;
  }[];
  rank_ic_series: { fold: number | null; window: string[]; rank_ic: number | null }[];
  counts: { effective: number[]; refuted: number[]; insufficient_evidence: number[] };
  disclosure: {
    power_warning: string | null;
    contamination: string | null;
    contamination_addendum: string | null;
    descriptive_observation: string | null;
    upstream_authority: string | null;
    not_claimed: string[];
  };
  flags: {
    no_new_effectiveness_claim: boolean;
    no_pooled_p_value: boolean;
    no_cross_round_sequential_claim: boolean;
  };
  freeze_fingerprint: string | null;
  source_round: string | null;
  source_certification_sha256: string | null;
  source_sha256: string | null;
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body: { detail?: string } = await response.json();
      message = body.detail ?? message;
    } catch {
      // The response may be a non-JSON proxy error.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", body: form });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body: { detail?: string } = await response.json();
      message = body.detail ?? message;
    } catch {
      // The response may be a non-JSON proxy error.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

async function deleteJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "DELETE" });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload: { detail?: string } = await response.json();
      message = payload.detail ?? message;
    } catch {
      // The response may be a non-JSON proxy error.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload: { detail?: string } = await response.json();
      message = payload.detail ?? message;
    } catch {
      // The response may be a non-JSON proxy error.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload: { detail?: string } = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload: { detail?: string } = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export interface DecisionRecord {
  record_id: string;
  choice: "subjective" | "quantitative" | "both" | "neither" | "defer";
  rationale: string;
  subjective_fingerprint: string | null;
  quantitative_fingerprint: string | null;
  decision_time: string;
  fingerprint: string;
}

export interface DecisionInput {
  choice: DecisionRecord["choice"];
  rationale: string;
  subjective_fingerprint?: string | null;
  quantitative_fingerprint?: string | null;
}

export interface SubjectiveInputPayload {
  decision_time?: string;
  symbols?: string[];
  live_news?: boolean;
  sentiment_snapshot?: Record<string, unknown> | null;
  a_share_summary?: Record<string, unknown> | null;
  strategy_query?: string;
  strategy_top_k?: number;
}

export interface LivingStrategy {
  entry_id: string;
  name: string;
  author: string | null;
  method: string;
  regimes: string[];
  source_url: string;
  source_name: string;
  published_at: string | null;
  collected_at: string;
  available_at: string;
  summary: string;
  relevance?: number;
  tag_overlap?: number;
}

export interface ExperienceStar {
  strategy_id: string;
  success_weight: number;
  failure_weight: number;
  evidence_weight: number;
  wilson_lower: number;
  stars: number;
  has_evidence: boolean;
  report_only: boolean;
}

export interface StrategyLibrarySnapshot {
  schema: string;
  count: number;
  entries: LivingStrategy[];
  experience: Record<string, ExperienceStar>;
  not_a_claim: string;
}

export const api = {
  subjectiveInputs: (payload: SubjectiveInputPayload) =>
    postJson<Record<string, unknown>>("/api/subjective/inputs", payload),
  subjectiveLlmConfig: () =>
    getJson<{ enabled: boolean; endpoint: string; publishableKey: string; note: string }>(
      "/api/subjective/llm-config",
    ),
  strategyLibrary: () =>
    getJson<StrategyLibrarySnapshot>("/api/strategy-library"),
  strategyRetrieve: (payload: { query: string; decision_time?: string; top_k?: number }) =>
    postJson<LivingStrategy[]>("/api/strategy-library/retrieve", payload),
  strategyRefresh: (payload: {
    query: string;
    collected_at: string;
    candidates: Array<Record<string, unknown>>;
    extractor_version?: string;
    prompt_version?: string;
  }) => postJson<{ status: { available: boolean; reason: string | null }; created: number }>(
    "/api/strategy-library/refresh", payload,
  ),
  decisions: () => getJson<DecisionRecord[]>("/api/decisions"),
  recordDecision: (input: DecisionInput) =>
    postJson<DecisionRecord>("/api/decisions", input),
  evidenceRounds: () => getJson<EvidenceRoundSummary[]>("/api/evidence/rounds"),
  evidenceRound: (roundId: string) =>
    getJson<EvidenceRoundDetail>(
      `/api/evidence/rounds/${encodeURIComponent(roundId)}`,
    ),
  evidenceExecutions: () => getJson<ExecutionDemoSummary[]>("/api/evidence/executions"),
  evidenceExecution: (demoId: string) =>
    getJson<ExecutionDemoDetail>(
      `/api/evidence/executions/${encodeURIComponent(demoId)}`,
    ),
  walkforwardRounds: () => getJson<WalkforwardSummary[]>("/api/evidence/walkforward"),
  walkforwardDetail: (directory: string) =>
    getJson<WalkforwardDetail>(
      `/api/evidence/walkforward/${encodeURIComponent(directory)}`,
    ),
  apiSources: () => getJson<ApiSource[]>("/api/data/api-sources"),
  saveApiSource: (input: ApiSourceInput) =>
    postJson<ApiSource>("/api/data/api-sources", input),
  updateApiSource: (key: string, input: ApiSourceInput) =>
    putJson<ApiSource>(
      `/api/data/api-sources/${encodeURIComponent(key)}`,
      input,
    ),
  deleteApiSource: (key: string) =>
    deleteJson<{ status: string; key: string }>(
      `/api/data/api-sources/${encodeURIComponent(key)}`,
    ),
  sources: () => getJson<DataSource[]>("/api/data/sources"),
  datasets: () => getJson<Dataset[]>("/api/data/datasets"),
  archivedDatasets: () =>
    getJson<Dataset[]>("/api/data/datasets/archived"),
  updateDataset: (datasetId: string, input: { name?: string; description?: string }) =>
    patchJson<Dataset>(
      `/api/data/datasets/${encodeURIComponent(datasetId)}`,
      input,
    ),
  archiveDataset: (datasetId: string) =>
    deleteJson<{ status: string; dataset_id: string }>(
      `/api/data/datasets/${encodeURIComponent(datasetId)}`,
    ),
  restoreDataset: (datasetId: string) =>
    postJson<{ status: string; dataset_id: string }>(
      `/api/data/datasets/${encodeURIComponent(datasetId)}/restore`,
      {},
    ),
  purgeDataset: (datasetId: string) =>
    deleteJson<{
      status: string;
      dataset_id: string;
      deleted_versions: number;
      deleted_objects: number;
      deleted_bytes: number;
      deleted_metadata: number;
    }>(`/api/data/datasets/${encodeURIComponent(datasetId)}/purge`),
  versions: (datasetId: string) =>
    getJson<DatasetVersion[]>(
      `/api/data/datasets/${encodeURIComponent(datasetId)}/versions`,
    ),
  snapshots: () => getJson<DatasetSnapshot[]>("/api/data/snapshots"),
  lineages: () => getJson<ProcessingLineage[]>("/api/data/lineages"),
  qualityReports: () => getJson<QualityReport[]>("/api/data/quality-reports"),
  datasetPreview: (datasetId: string, versionId: string, partitionId = "all", missingPolicy: "common" | "blank" = "common") =>
    getJson<CsvPreview>(
      `/api/data/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/preview?partition_id=${encodeURIComponent(partitionId)}&missing_policy=${missingPolicy}`,
    ),
  columnDistribution: (datasetId: string, versionId: string, column: string, partitionId = "all") =>
    getJson<ColumnDistribution>(
      `/api/data/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/distribution?partition_id=${encodeURIComponent(partitionId)}&column=${encodeURIComponent(column)}`,
    ),
  importCsv: (input: {
    datasetId: string;
    datasetName: string;
    file: File;
    encoding?: string;
    delimiter?: string;
    qualityPolicy: QualityPolicy;
  }) => {
    const form = new FormData();
    form.set("dataset_id", input.datasetId);
    form.set("dataset_name", input.datasetName);
    form.set("file", input.file);
    form.set("encoding", input.encoding ?? "auto");
    form.set("delimiter", input.delimiter ?? "auto");
    form.set("quality_policy", input.qualityPolicy);
    return postForm<CsvImportResult>("/api/data/import/csv", form);
  },
  importSource: (input: {
    sourceType: string;
    spec: Record<string, unknown>;
    datasetId: string;
    datasetName: string;
    qualityPolicy: QualityPolicy;
    mode?: string;
    cursor?: string;
    formatId?: string;
    partitionId?: string;
  }) =>
    postJson<SourceImportResult>("/api/data/import/source", {
      source_type: input.sourceType,
      spec: input.spec,
      dataset_id: input.datasetId,
      dataset_name: input.datasetName,
      quality_policy: input.qualityPolicy,
      mode: input.mode ?? "batch",
      cursor: input.cursor || null,
      format_id: input.formatId || null,
      partition_id: input.partitionId || "all",
    }),
  backtestConfigs: () =>
    getJson<BacktestConfigRecord[]>("/api/backtests/configs"),
  saveBacktestConfig: (input: BacktestConfigInput) =>
    postJson<BacktestConfigRecord>("/api/backtests/configs", input),
  updateBacktestConfig: (configId: string, input: BacktestConfigInput) =>
    putJson<BacktestConfigRecord>(
      `/api/backtests/configs/${encodeURIComponent(configId)}`,
      input,
    ),
  deleteBacktestConfig: (configId: string) =>
    deleteJson<{ status: string; config_id: string }>(
      `/api/backtests/configs/${encodeURIComponent(configId)}`,
    ),
  backtestStrategies: () => getJson<string[]>("/api/backtests/strategies"),
  backtestSources: () => getJson<BacktestSource[]>("/api/backtests/sources"),
  strategyCatalog: () =>
    getJson<StrategyCatalogEntry[]>("/api/backtests/strategy-catalog"),
  quickRun: (input: QuickRunInput) =>
    postJson<BacktestRunResponse>("/api/backtests/quick-run", input),
  runBacktest: (
    configId: string,
    window?: { start?: string | null; end?: string | null },
  ) =>
    postJson<BacktestRunResponse>("/api/backtests/run", {
      config_id: configId,
      ...(window ?? {}),
    }),
  backtestResults: () =>
    getJson<BacktestResultSummary[]>("/api/backtests/results"),
  backtestResult: (runId: string) =>
    getJson<BacktestResultDetail>(
      `/api/backtests/results/${encodeURIComponent(runId)}`,
    ),
  saveViewConfig: (runId: string, visiblePanes: string[]) =>
    putJson<{ run_id: string; view_config: BacktestViewConfig }>(
      `/api/backtests/results/${encodeURIComponent(runId)}/view-config`,
      { visible_panes: visiblePanes },
    ),
  experiments: () => getJson<Experiment[]>("/api/experiments"),
  runs: (experimentId: string) =>
    getJson<ExperimentRun[]>(
      `/api/experiments/${encodeURIComponent(experimentId)}/runs`,
    ),
  run: (runId: string) =>
    getJson<ExperimentRun>(`/api/runs/${encodeURIComponent(runId)}`),
  result: (runId: string) =>
    getJson<ExperimentResult | null>(
      `/api/runs/${encodeURIComponent(runId)}/result`,
    ),
  runtime: () => getJson<RuntimePayload>("/api/runtime"),
  settings: () => getJson<SettingsPayload>("/api/settings"),
  loopRuns: () => getJson<LoopRunSummary[]>("/api/loop/runs"),
  loopRun: (fingerprint: string) =>
    getJson<LoopRunDetail>(
      `/api/loop/runs/${encodeURIComponent(fingerprint)}`,
    ),
  runLoop: (input: LoopRunInput) =>
    postJson<LoopRunDetail>("/api/loop/runs", input),
};

export interface LoopRunInput {
  source_key?: string | null;
  symbol?: string;
  start?: string;
  end?: string;
  frequency?: string;
  adjust?: string;
  seed?: number;
  rounds?: number;
  group_size?: number;
  generator?: string;
  features?: string[] | null;
  windows?: number[] | null;
  bias_magnitude?: number;
  bias_mode?: string;
  proxy_reps?: number;
  proxy_block_size?: number;
  statistical_reps?: number;
  statistical_block_size?: number;
  alpha?: number;
  direction_strength?: number;
  experiment_id?: string;
}

export interface LoopRunSummary {
  fingerprint: string;
  origin: string;
  created_at: string;
  round_count: number;
  final_reliability: number | null;
  run_ids: string[];
  experiment_id: string | null;
}

export interface LoopStageRecord {
  stage: string;
  status: string;
  fingerprint: string | null;
  attempts: number;
  spec: Record<string, unknown>;
}

export interface LoopRoundRecord {
  round_index: number;
  stages: LoopStageRecord[];
  spec: Record<string, unknown>;
  run_id: string;
}

export interface LoopRunResult {
  fingerprint: string;
  rounds: LoopRoundRecord[];
  final_policy: Record<string, unknown> & { version?: number; weights?: Record<string, number> };
  final_calibration: Record<string, unknown> & { version?: number; bias_offset?: number | null };
  final_reliability: number;
  run_ids: string[];
  spec: Record<string, unknown> & {
    config?: Record<string, unknown>;
    stage_order?: string[];
  };
  environment: Record<string, unknown>;
}

export interface LoopRunDetail {
  fingerprint: string;
  origin: string;
  created_at: string;
  round_count: number;
  final_reliability: number | null;
  run_ids: string[];
  experiment_id: string | null;
  result: LoopRunResult;
}
