import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive, Network } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { SelectField } from "../../../components/ui/SelectField";
import { Button } from "../../../components/ui/Button";
import { Panel } from "../../../components/shared/Panel";
import { EmptyState, ErrorState } from "../../../components/shared/States";
import {
  api,
  type ApiSource,
  type ApiSourceInput,
  type Dataset,
  type QualityPolicy,
} from "../../api";
import { CsvImportForm } from "./CsvImportForm";
import { useTranslation } from "react-i18next";

type SourceKind = "local" | "api";
type SourceRow = ApiSource & { kind: SourceKind; builtIn?: boolean };

const fieldClassName =
  "mt-1 min-h-10 w-full rounded-md border border-line bg-canvas px-3 text-sm text-ink placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

const emptyForm = {
  key: "",
  name: "",
  url: "",
  method: "GET" as "GET" | "POST",
  query: "",
  headers: "",
  body: "",
  credentialValue: "",
  credentialEnv: "",
  credentialName: "Authorization",
  credentialIn: "header" as "header" | "query",
  cursorParam: "cursor",
  timeout: "30",
};

type FormState = typeof emptyForm;

function parseMapping(text: string, label: string): Record<string, string> {
  if (!text.trim()) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
    result[key] = typeof value === "string" ? value : String(value);
  }
  return result;
}

function mappingText(value: Record<string, string> | undefined): string {
  return value && Object.keys(value).length ? JSON.stringify(value, null, 2) : "";
}

function sourceIdOf(source: SourceRow): string {
  return source.builtIn
    ? "local-upload"
    : `${source.kind}-${source.key}`;
}

function datasetIdOf(source: SourceRow): string {
  return `ds-${source.key}`;
}

// The symbol in `param` identifies the subject of a fetch, so each symbol gets
// its own dataset by default. A per-request `param` overrides the saved one.
function symbolOf(source: SourceRow, requestSpec: string): string {
  let param = source.query?.param ?? "";
  try {
    const parsed: unknown = JSON.parse(requestSpec || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const value = (parsed as Record<string, unknown>).param;
      if (typeof value === "string" && value.trim()) param = value.trim();
    }
  } catch {
    // Keep the saved param while the JSON is still being typed.
  }
  return param.split(",")[0].trim();
}

function defaultDatasetId(source: SourceRow, requestSpec: string): string {
  const symbol = symbolOf(source, requestSpec);
  return symbol ? `ds-${symbol}` : datasetIdOf(source);
}

function defaultDatasetName(source: SourceRow, requestSpec: string): string {
  const symbol = symbolOf(source, requestSpec);
  return symbol ? `${symbol} daily` : `${source.key} dataset`;
}

export function DataManagement() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const saved = useQuery({ queryKey: ["data", "api-sources"], queryFn: api.apiSources });
  const datasets = useQuery({ queryKey: ["data", "datasets"], queryFn: api.datasets });
  const archived = useQuery({
    queryKey: ["data", "datasets", "archived"],
    queryFn: api.archivedDatasets,
  });

  const [editor, setEditor] = useState<{ kind: SourceKind; key: string | null } | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [formError, setFormError] = useState<string>();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [fetchKey, setFetchKey] = useState<string | null>(null);
  const [requestSpec, setRequestSpec] = useState("{}");
  const [dataFormat, setDataFormat] = useState("");
  const [qualityPolicy, setQualityPolicy] = useState<QualityPolicy>("report_only");
  const [datasetIdOverride, setDatasetIdOverride] = useState<string | null>(null);
  const [datasetNameOverride, setDatasetNameOverride] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; value: string } | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<string | null>(null);
  const [notice, setNotice] = useState<string>();

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function refresh() {
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: ["data", "api-sources"] }),
      queryClient.invalidateQueries({ queryKey: ["data", "datasets"] }),
      queryClient.invalidateQueries({ queryKey: ["data", "datasets", "archived"] }),
      queryClient.invalidateQueries({ queryKey: ["data", "sources"] }),
    ]);
  }

  const saveMutation = useMutation({
    mutationFn: (input: { key: string | null; payload: ApiSourceInput }) =>
      input.key === null
        ? api.saveApiSource(input.payload)
        : api.updateApiSource(input.key, input.payload),
    onSuccess: async (savedSource) => {
      setEditor(null);
      setForm(emptyForm);
      setNotice(`Source '${savedSource.key}' saved.`);
      await refresh();
    },
  });

  const deleteSourceMutation = useMutation({
    mutationFn: (key: string) => api.deleteApiSource(key),
    onSuccess: async () => {
      setNotice("Source removed. Its published datasets are untouched.");
      await refresh();
    },
  });

  const importMutation = useMutation({
    mutationFn: (input: Parameters<typeof api.importSource>[0]) =>
      api.importSource(input),
    onSuccess: async (result) => {
      setNotice(`Published ${result.dataset_id}@${result.version_id}.`);
      await refresh();
    },
  });

  const renameMutation = useMutation({
    mutationFn: (input: { id: string; name: string }) =>
      api.updateDataset(input.id, { name: input.name }),
    onSuccess: async () => {
      setRenaming(null);
      await refresh();
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (datasetId: string) => api.archiveDataset(datasetId),
    onSuccess: async () => {
      setNotice("Dataset archived. You can restore it below.");
      await refresh();
    },
  });

  const restoreMutation = useMutation({
    mutationFn: (datasetId: string) => api.restoreDataset(datasetId),
    onSuccess: async () => {
      await refresh();
    },
  });

  const purgeMutation = useMutation({
    mutationFn: (datasetId: string) => api.purgeDataset(datasetId),
    onSuccess: async (result) => {
      setPurgeTarget(null);
      setNotice(
        `Permanently deleted '${result.dataset_id}': ${result.deleted_versions} version(s), ${result.deleted_objects} stored file(s), ${result.deleted_metadata} metadata record(s).`,
      );
      await refresh();
    },
  });

  const rows: SourceRow[] = (saved.data ?? []).map((source) => ({
    ...source,
    kind: source.kind ?? "api",
  }));
  const uploaded: SourceRow = {
    key: "__uploaded__",
    name: "Uploaded files",
    url: "Browser uploads and datasets whose source was removed",
    kind: "local",
    builtIn: true,
    method: "GET",
    query: {},
    headers: {},
    body: null,
    credential_value: null,
    credential_env: null,
    credential_name: "Authorization",
    credential_in: "header",
    cursor_param: "cursor",
    timeout: 30,
  };
  const localRows = [uploaded, ...rows.filter((row) => row.kind === "local")];
  const apiRows = rows.filter((row) => row.kind === "api");
  const allDatasets = datasets.data ?? [];

  function datasetsUnder(source: SourceRow): Dataset[] {
    if (source.builtIn) {
      const known = new Set(rows.map(sourceIdOf));
      return allDatasets.filter(
        (dataset) =>
          dataset.source_ids.includes("local-upload") ||
          !dataset.source_ids.some((id) => known.has(id)),
      );
    }
    const id = sourceIdOf(source);
    return allDatasets.filter((dataset) => dataset.source_ids.includes(id));
  }

  function openNew(kind: SourceKind) {
    setEditor({ kind, key: null });
    setForm(emptyForm);
    setFormError(undefined);
  }

  function openEdit(source: SourceRow) {
    setEditor({ kind: source.kind, key: source.key });
    setForm({
      key: source.key,
      name: source.name,
      url: source.url,
      method: source.method,
      query: mappingText(source.query),
      headers: mappingText(source.headers),
      body: source.body ?? "",
      credentialValue: source.credential_value ?? "",
      credentialEnv: source.credential_env ?? "",
      credentialName: source.credential_name,
      credentialIn: source.credential_in,
      cursorParam: source.cursor_param,
      timeout: String(source.timeout),
    });
    setFormError(undefined);
  }

  function submitSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(undefined);
    if (!editor) return;
    try {
      const payload: ApiSourceInput = {
        key: form.key.trim(),
        name: form.name.trim() || form.key.trim(),
        url: form.url.trim(),
        kind: editor.kind,
        method: form.method,
        query: parseMapping(form.query, "Query parameters"),
        headers: parseMapping(form.headers, "Headers"),
        body: form.body || null,
        credential_value: form.credentialValue || null,
        credential_env: form.credentialEnv.trim() || null,
        credential_name: form.credentialName.trim() || "Authorization",
        credential_in: form.credentialIn,
        cursor_param: form.cursorParam.trim() || "cursor",
        timeout: Number(form.timeout) || 30,
      };
      saveMutation.mutate({ key: editor.key, payload });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Invalid configuration.");
    }
  }

  function submitFetch(source: SourceRow) {
    let spec: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(requestSpec || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Per-request parameters must be a JSON object.");
      }
      spec = parsed as Record<string, unknown>;
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Invalid JSON.");
      return;
    }
    const datasetId = (datasetIdOverride ?? defaultDatasetId(source, requestSpec)).trim();
    if (!datasetId) {
      setFormError("Dataset ID is required.");
      return;
    }
    const datasetName =
      (datasetNameOverride ?? defaultDatasetName(source, requestSpec)).trim() || datasetId;
    setFormError(undefined);
    importMutation.mutate({
      sourceType: source.key,
      spec,
      datasetId,
      datasetName,
      qualityPolicy,
      formatId: dataFormat,
    });
  }

  function toggle(key: string) {
    setExpanded((current) => ({ ...current, [key]: current[key] === false }));
  }

  function renderDataset(dataset: Dataset) {
    const isRenaming = renaming?.id === dataset.dataset_id;
    return (
      <li key={dataset.dataset_id} className="rounded-md border border-line bg-surface/40">
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
          <div className="min-w-0">
            {isRenaming ? (
              <input
                className="min-h-9 w-56 rounded-md border border-line bg-canvas px-2 text-sm text-ink"
                aria-label={t("New dataset name")}
                value={renaming.value}
                onChange={(event) =>
                  setRenaming({ id: dataset.dataset_id, value: event.target.value })
                }
              />
            ) : (
              <Link
                className="block truncate text-sm font-medium text-ink underline-offset-4 hover:text-accent hover:underline"
                to={`/data/datasets/${encodeURIComponent(dataset.dataset_id)}/preview`}
              >
                {dataset.name}
              </Link>
            )}
            <p className="mt-0.5 break-all font-mono text-[13px] text-muted">
              {dataset.dataset_id}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {isRenaming ? (
              <>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={renameMutation.isPending || !renaming.value.trim()}
                  onClick={() =>
                    renameMutation.mutate({
                      id: dataset.dataset_id,
                      name: renaming.value.trim(),
                    })
                  }
                >
                  {t("Save name")}
                </Button>
                <Button size="sm" onClick={() => setRenaming(null)}>
                  {t("Cancel")}
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  onClick={() =>
                    setRenaming({ id: dataset.dataset_id, value: dataset.name })
                  }
                >
                  {t("Rename")}
                </Button>
                <Button
                  size="sm"
                  disabled={archiveMutation.isPending}
                  onClick={() => archiveMutation.mutate(dataset.dataset_id)}
                >
                  {t("Archive")}
                </Button>
              </>
            )}
          </div>
        </div>

      </li>
    );
  }

  function renderSource(source: SourceRow) {
    const isExpanded = expanded[source.key] !== false;
    const children = datasetsUnder(source);
    const isFetching = fetchKey === source.key;
    return (
      <li key={source.key} className="rounded-lg border border-line bg-canvas/40">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <button
            type="button"
            className="min-w-0 flex-1 text-left"
            aria-expanded={isExpanded}
            onClick={() => toggle(source.key)}
          >
            <p className="text-sm font-semibold text-ink">
              {source.name}
              <span className="ml-2 font-mono text-[13px] font-normal text-muted">
                {source.key === "__uploaded__" ? "" : source.key}
              </span>
            </p>
            <p className="mt-1 break-all text-[13px] leading-5 text-muted">
              {source.kind === "local" ? "Path: " : `${source.method} `}
              {source.url}
            </p>
            <p className="mt-1 text-[13px] text-muted">
              {children.length} dataset{children.length === 1 ? "" : "s"} ·{" "}
              {isExpanded ? "Hide" : "Show"}
            </p>
          </button>
          <div className="flex shrink-0 flex-wrap gap-2">
            {source.builtIn ? (
              <Button size="sm" onClick={() => setUploadOpen((value) => !value)}>
                {uploadOpen ? "Close upload" : "Upload CSV"}
              </Button>
            ) : (
              <>
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    setFetchKey(isFetching ? null : source.key);
                    setDataFormat(source.kind === "local" ? "csv" : "");
                    setRequestSpec("{}");
                    setDatasetIdOverride(null);
                    setDatasetNameOverride(null);
                    setFormError(undefined);
                  }}
                >
                  {isFetching ? "Close fetch" : "Fetch data"}
                </Button>
                <Button size="sm" onClick={() => openEdit(source)}>
                  {t("Edit")}
                </Button>
                <Button
                  size="sm"
                  disabled={deleteSourceMutation.isPending}
                  onClick={() => deleteSourceMutation.mutate(source.key)}
                >
                  {t("Remove")}
                </Button>
              </>
            )}
          </div>
        </div>

        {isExpanded && (
          <div className="border-t border-line px-4 py-3">
            <p className="mb-2 text-[13px] font-semibold text-ink">{t("Datasets")}</p>
            {children.length ? (
              <ul className="grid gap-2">{children.map(renderDataset)}</ul>
            ) : (
              <p className="text-[13px] leading-5 text-muted">
                {t("No datasets from this source yet. Fetch data to publish the first version.")}
              </p>
            )}

            {source.builtIn && uploadOpen && (
              <div className="mt-3 rounded-lg border border-line bg-surface/40 p-3">
                <CsvImportForm
                  onImported={() => {
                    setUploadOpen(false);
                    void refresh();
                  }}
                />
              </div>
            )}

            {!source.builtIn && isFetching && (
              <form
                className="mt-3 grid gap-3 rounded-lg border border-line bg-surface/40 p-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  submitFetch(source);
                }}
              >
                <label className="text-[13px] font-medium text-ink">
                  Per-request parameters (JSON)
                  <textarea
                    className={`${fieldClassName} min-h-16 resize-y font-mono text-[13px]`}
                    aria-label={t("Per-request parameters (JSON)")}
                    placeholder={'{"param": "sh600000,day,2024-01-01,2024-06-28,320,qfq"}'}
                    value={requestSpec}
                    onChange={(event) => setRequestSpec(event.target.value)}
                  />
                </label>
                <p className="text-xs leading-5 text-muted">
                  Leave empty to use the saved source query. For the Tencent K-line source,
                  {" "}<span className="font-mono">param</span> is{" "}
                  <span className="font-mono">{t("symbol,frequency,start,end,limit,adjust")}</span>
                  {" "}(frequency: day / week / month; adjust: qfq / hfq / empty).
                </p>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="text-[13px] font-medium text-ink">
                    {t("Dataset ID")}
                    <input
                      className={`${fieldClassName} font-mono text-[13px]`}
                      aria-label={t("Dataset ID")}
                      value={datasetIdOverride ?? defaultDatasetId(source, requestSpec)}
                      onChange={(event) => setDatasetIdOverride(event.target.value)}
                    />
                  </label>
                  <label className="text-[13px] font-medium text-ink">
                    {t("Dataset name")}
                    <input
                      className={fieldClassName}
                      aria-label={t("Dataset name")}
                      value={datasetNameOverride ?? defaultDatasetName(source, requestSpec)}
                      onChange={(event) => setDatasetNameOverride(event.target.value)}
                    />
                  </label>
                </div>
                <p className="text-[13px] leading-5 text-muted">
                  Same ID publishes a new version; a different ID creates a separate dataset.
                  Defaults follow the symbol in <span className="font-mono">param</span>.
                </p>
                <div className="grid gap-3 md:grid-cols-2">
                  <SelectField
                    label={t("Data format")}
                    value={dataFormat}
                    onChange={setDataFormat}
                    options={[
                      { value: "", label: t("Raw bytes (freeze as-is)") },
                      { value: "csv", label: t("CSV (parse into columns)") },
                      {
                        value: "kline-json",
                        label: t("A-share K-line (JSON to table)"),
                      },
                    ]}
                  />
                  <SelectField
                    label={t("Quality policy")}
                    value={qualityPolicy}
                    onChange={(value) => setQualityPolicy(value as QualityPolicy)}
                    options={[
                      { value: "report_only", label: t("Report only (always publish)") },
                      { value: "gate_on_fail", label: t("Gate on FAIL (retract version)") },
                    ]}
                  />
                </div>
                <div>
                  <Button type="submit" variant="primary" disabled={importMutation.isPending}>
                    {importMutation.isPending ? "Fetching…" : "Fetch and publish"}
                  </Button>
                </div>
              </form>
            )}
          </div>
        )}
      </li>
    );
  }

  function renderBlock(kind: SourceKind, title: string, description: string, items: SourceRow[]) {
    return (
      <Panel
        title={title}
        description={description}
        actions={
          <Button size="sm" variant="primary" onClick={() => openNew(kind)}>
            {kind === "local" ? "New local source" : "New API source"}
          </Button>
        }
      >
        <div className="mb-4 flex items-center gap-2 text-[13px] text-muted">
          {kind === "local" ? (
            <HardDrive aria-hidden className="h-4 w-4" />
          ) : (
            <Network aria-hidden className="h-4 w-4" />
          )}
          <span>{items.length} source{items.length === 1 ? "" : "s"}</span>
        </div>
        {items.length ? (
          <ul className="grid gap-3">{items.map(renderSource)}</ul>
        ) : (
          <EmptyState
            title={t("No sources yet")}
            description={t("Add a source, then fetch data from it to create datasets.")}
          />
        )}
      </Panel>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-ink">{t("Data management")}</h2>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted">
          A data source is where data comes from. Datasets live under their source;
          each fetch publishes a new immutable version.
        </p>
      </div>

      {editor && (
        <Panel
          title={editor.key ? `Edit ${editor.kind === "local" ? "local" : "API"} source` : `New ${editor.kind === "local" ? "local" : "API"} source`}
          description={t("Saved sources stay here after a restart. Credentials are stored on the server only.")}
          actions={<Button size="sm" onClick={() => setEditor(null)}>{t("Cancel")}</Button>}
        >
          <form className="grid gap-4" onSubmit={submitSource}>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="text-[13px] font-medium text-ink">
                {t("Source ID")}
                <input
                  className={fieldClassName}
                  aria-label={t("Source ID")}
                  placeholder={editor.kind === "local" ? "campus_csv" : "campus_api"}
                  value={form.key}
                  disabled={editor.key !== null}
                  onChange={(event) => update("key", event.target.value)}
                />
              </label>
              <label className="text-[13px] font-medium text-ink">
                {t("Display name")}
                <input
                  className={fieldClassName}
                  aria-label={t("Display name")}
                  placeholder={t("Campus data")}
                  value={form.name}
                  onChange={(event) => update("name", event.target.value)}
                />
              </label>
              <label className="text-[13px] font-medium text-ink md:col-span-2">
                {editor.kind === "local" ? "File path" : "API URL"}
                <input
                  className={fieldClassName}
                  aria-label={editor.kind === "local" ? "File path" : "API URL"}
                  placeholder={
                    editor.kind === "local"
                      ? "E:/data/csmar_daily.csv"
                      : "https://api.example.com/v1/series"
                  }
                  value={form.url}
                  onChange={(event) => update("url", event.target.value)}
                />
              </label>

              {editor.kind === "api" && (
                <>
                  <SelectField
                    label={t("Method")}
                    value={form.method}
                    onChange={(value) => update("method", value as "GET" | "POST")}
                    options={[
                      { value: "GET", label: "GET" },
                      { value: "POST", label: "POST" },
                    ]}
                  />
                  <label className="text-[13px] font-medium text-ink">
                    API key / token (optional)
                    <input
                      className={fieldClassName}
                      aria-label={t("API key / token (optional)")}
                      type="password"
                      value={form.credentialValue}
                      onChange={(event) => update("credentialValue", event.target.value)}
                    />
                  </label>
                  <label className="text-[13px] font-medium text-ink">
                    Query parameters (JSON)
                    <textarea
                      className={`${fieldClassName} min-h-20 resize-y font-mono text-[13px]`}
                      aria-label={t("Query parameters (JSON)")}
                      placeholder={'{"symbol": "000001.SZ"}'}
                      value={form.query}
                      onChange={(event) => update("query", event.target.value)}
                    />
                  </label>
                  <label className="text-[13px] font-medium text-ink">
                    Headers (JSON)
                    <textarea
                      className={`${fieldClassName} min-h-20 resize-y font-mono text-[13px]`}
                      aria-label={t("Headers (JSON)")}
                      placeholder={'{"User-Agent": "Mozilla/5.0"}'}
                      value={form.headers}
                      onChange={(event) => update("headers", event.target.value)}
                    />
                  </label>
                  <details className="md:col-span-2 rounded-md border border-line bg-canvas/40 px-3 py-2">
                    <summary className="cursor-pointer text-[13px] font-medium text-ink">
                      {t("Advanced options")}
                    </summary>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <label className="text-[13px] font-medium text-ink">
                        {t("Credential environment variable")}
                        <input
                          className={fieldClassName}
                          aria-label={t("Credential environment variable")}
                          value={form.credentialEnv}
                          onChange={(event) => update("credentialEnv", event.target.value)}
                        />
                      </label>
                      <label className="text-[13px] font-medium text-ink">
                        {t("Credential field name")}
                        <input
                          className={fieldClassName}
                          aria-label={t("Credential field name")}
                          value={form.credentialName}
                          onChange={(event) => update("credentialName", event.target.value)}
                        />
                      </label>
                      <SelectField
                        label={t("Credential goes in")}
                        value={form.credentialIn}
                        onChange={(value) => update("credentialIn", value as "header" | "query")}
                        options={[
                          { value: "header", label: t("Request header") },
                          { value: "query", label: t("Query parameter") },
                        ]}
                      />
                      <label className="text-[13px] font-medium text-ink">
                        {t("Cursor parameter")}
                        <input
                          className={fieldClassName}
                          aria-label={t("Cursor parameter")}
                          value={form.cursorParam}
                          onChange={(event) => update("cursorParam", event.target.value)}
                        />
                      </label>
                      <label className="text-[13px] font-medium text-ink">
                        Timeout (seconds)
                        <input
                          className={fieldClassName}
                          aria-label={t("Timeout (seconds)")}
                          type="number"
                          min={1}
                          max={300}
                          value={form.timeout}
                          onChange={(event) => update("timeout", event.target.value)}
                        />
                      </label>
                      <label className="text-[13px] font-medium text-ink md:col-span-2">
                        POST body (optional)
                        <textarea
                          className={`${fieldClassName} min-h-16 resize-y font-mono text-[13px]`}
                          aria-label={t("POST body (optional)")}
                          value={form.body}
                          onChange={(event) => update("body", event.target.value)}
                        />
                      </label>
                    </div>
                  </details>
                </>
              )}
            </div>
            {formError && <ErrorState title={t("Invalid configuration")} description={formError} />}
            {saveMutation.error && (
              <ErrorState title={t("Could not save source")} description={saveMutation.error.message} />
            )}
            <div className="border-t border-line pt-4">
              <Button type="submit" variant="primary" disabled={saveMutation.isPending}>
                {saveMutation.isPending
                  ? "Saving…"
                  : editor.key
                    ? "Update source"
                    : "Save source"}
              </Button>
            </div>
          </form>
        </Panel>
      )}

      <div className="grid gap-5 xl:grid-cols-2">
        {renderBlock(
          "local",
          "Local sources",
          "Files on this machine, plus CSV files uploaded from your browser.",
          localRows,
        )}
        {renderBlock(
          "api",
          "API sources",
          "HTTP endpoints you connect once and fetch from anytime.",
          apiRows,
        )}
      </div>

      {notice && (
        <div className="rounded-lg border border-accent/30 bg-elevated/30 px-4 py-3 text-[13px] text-ink">
          {notice}
        </div>
      )}
      {[saveMutation, deleteSourceMutation, importMutation, renameMutation, archiveMutation, restoreMutation, purgeMutation]
        .filter((mutation) => mutation.error)
        .map((mutation, index) => (
          <ErrorState key={index} title={t("Operation failed")} description={mutation.error!.message} />
        ))}

      <details className="rounded-lg border border-line bg-canvas/40 px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-ink">
          Archived datasets ({(archived.data ?? []).length})
        </summary>
        {(archived.data ?? []).length ? (
          <ul className="mt-3 grid gap-2">
            {archived.data!.map((dataset) => {
              const confirming = purgeTarget === dataset.dataset_id;
              return (
                <li
                  key={dataset.dataset_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-surface/40 px-3 py-2"
                >
                  <span className="min-w-0 text-sm text-ink">
                    {dataset.name}
                    <span className="ml-2 font-mono text-[13px] text-muted">
                      {dataset.dataset_id}
                    </span>
                  </span>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {confirming ? (
                      <>
                        <Button
                          size="sm"
                          disabled={purgeMutation.isPending}
                          onClick={() => purgeMutation.mutate(dataset.dataset_id)}
                        >
                          {t("Yes, delete forever")}
                        </Button>
                        <Button size="sm" onClick={() => setPurgeTarget(null)}>
                          {t("Cancel")}
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button
                          size="sm"
                          disabled={restoreMutation.isPending}
                          onClick={() => restoreMutation.mutate(dataset.dataset_id)}
                        >
                          {t("Restore")}
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => setPurgeTarget(dataset.dataset_id)}
                        >
                          {t("Delete permanently")}
                        </Button>
                      </>
                    )}
                  </div>
                  {confirming && (
                    <p className="w-full text-[13px] font-medium text-ink">
                      Permanent deletion cannot be undone. Removes the dataset
                      definition, every version and its stored bytes. Content shared
                      with other datasets is kept.
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-2 text-[13px] text-muted">
            Nothing archived. Archiving only hides a dataset; use Delete permanently
            to remove it for good.
          </p>
        )}
      </details>
    </div>
  );
}
