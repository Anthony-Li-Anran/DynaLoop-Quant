import { BRAND } from "../app/brand";
import { PageHeader } from "../components/shared/PageHeader";
import { useQueries, useQuery } from "@tanstack/react-query";
import { AlertCircle, Database, FlaskConical, Play, ServerCog } from "lucide-react";
import { Link } from "react-router-dom";
import { DataTable, type Column } from "../components/shared/DataTable";
import { TimeDisplay } from "../components/shared/Formatting";
import { OverviewMetric, OverviewPanel } from "../components/shared/OverviewPanel";
import { QueryState } from "../components/shared/States";
import { StatusBadge } from "../components/shared/StatusBadge";
import { api, type Dataset, type ExperimentRun } from "../features/api";
import { useTranslation } from "react-i18next";

type ExperimentSummary = { id: string; name: string; runs: ExperimentRun[] | undefined; error: boolean };
type TFunction = (key: string) => string;
const buildExperimentColumns = (t: TFunction): Column<ExperimentSummary>[] => [
  { key: "name", header: t("Experiment"), render: row => <Link className="hover:text-blue-400" to="/experiments">{row.name}</Link> },
  { key: "updated", header: t("Latest run"), render: row => row.runs?.[0] ? <TimeDisplay value={row.runs[0].created_at} /> : <span className="text-muted">—</span> },
  { key: "runs", header: t("Runs"), render: row => row.runs?.length ?? "—" },
  { key: "status", header: t("Latest run status"), render: row => row.error ? <span className="text-rose-300">{t("Unavailable")}</span> : row.runs?.[0] ? <StatusBadge status={row.runs[0].status} /> : <span className="text-muted">{row.runs ? t("No runs") : t("Loading…")}</span> },
];
const buildDatasetColumns = (t: TFunction): Column<Dataset>[] => [
  { key: "name", header: t("Dataset"), render: row => <Link className="hover:text-blue-400" to="/data">{row.name}</Link> },
  { key: "type", header: t("Type"), render: row => row.data_type ?? "—" },
  { key: "format", header: t("Format"), render: row => row.format_id ?? "—" },
];

export function OverviewPage() {
  const { t } = useTranslation();
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: api.experiments });
  const datasets = useQuery({ queryKey: ["data", "datasets"], queryFn: api.datasets });
  const runtime = useQuery({ queryKey: ["runtime"], queryFn: api.runtime });
  const runQueries = useQueries({ queries: (experiments.data ?? []).map(experiment => ({
    queryKey: ["experiments", experiment.experiment_id, "runs"],
    queryFn: () => api.runs(experiment.experiment_id),
  })) });
  const runsAvailable = experiments.isSuccess && runQueries.every(query => query.isSuccess);
  const allRuns = runQueries.flatMap(query => query.data ?? []);
  const runError = experiments.isError || runQueries.some(query => query.isError);
  const summaries = (experiments.data ?? []).map((experiment, index): ExperimentSummary => ({
    id: experiment.experiment_id, name: experiment.name, error: runQueries[index]?.isError ?? false,
    runs: runQueries[index]?.data?.slice().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
  })).sort((a, b) => (Date.parse(b.runs?.[0]?.created_at ?? "") || 0) - (Date.parse(a.runs?.[0]?.created_at ?? "") || 0));
  const modules = [
    { name: t("Data"), icon: Database, query: datasets, to: "/data" },
    { name: t("Experiment Management"), icon: FlaskConical, query: experiments, to: "/experiments" },
    { name: t("Runtime"), icon: ServerCog, query: runtime, to: "/runtime" },
  ];
  const experimentColumns = buildExperimentColumns(t);
  const datasetColumns = buildDatasetColumns(t);
  return <div className="research-overview">
    <PageHeader eyebrow={t("Research workspace / Overview")} title={t("Research overview")} description={`${BRAND.discipline} · ${t("Reproducible experiments and evidence.")}`} />
    <div className="metric-strip mb-4 grid grid-cols-2 sm:grid-cols-4">
      <OverviewMetric label={t("Experiments")} icon={FlaskConical} value={experiments.isSuccess ? experiments.data.length : undefined} note={t(experiments.isError ? "Unable to load experiments" : "Registered experiments")} />
      <OverviewMetric label={t("Datasets")} icon={Database} value={datasets.isSuccess ? datasets.data.length : undefined} note={t(datasets.isError ? "Unable to load datasets" : "Registered datasets")} />
      <OverviewMetric label={t("Completed Runs")} icon={Play} value={runsAvailable ? allRuns.filter(run => run.status === "completed").length : undefined} note={t(runError ? "Run totals unavailable" : "Across all recorded experiments")} />
      <OverviewMetric label={t("Failed Runs")} icon={AlertCircle} value={runsAvailable ? allRuns.filter(run => run.status === "failed").length : undefined} note={t(runError ? "Run totals unavailable" : "Across all recorded experiments")} />
    </div>
    <OverviewPanel title={t("Recent experiments")} to="/experiments">
      <QueryState query={experiments} emptyTitle={t("No experiments recorded")}>
        {() => <DataTable rows={summaries.slice(0, 4)} columns={experimentColumns} getRowKey={row => row.id} emptyTitle={t("No experiments recorded")} emptyDescription={t("Your recorded experiments and run history will appear here.")} />}
      </QueryState>
    </OverviewPanel>
    <div className="mt-4 grid gap-4 lg:grid-cols-[1.25fr_1fr]">
      <OverviewPanel title={t("Datasets")} to="/data">
        <QueryState query={datasets} emptyTitle={t("No datasets registered")}>
          {rows => <DataTable rows={rows.slice(0, 3)} columns={datasetColumns} getRowKey={row => row.dataset_id} emptyTitle={t("No datasets registered")} emptyDescription={t("Published research data will appear in the catalog.")} />}
        </QueryState>
      </OverviewPanel>
      <OverviewPanel title={t("System modules")}>
        <div className="divide-y divide-line">
          {modules.map(({ name, icon: Icon, query, to }) => <div key={name} className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0">
            <Link to={to} className="flex items-center gap-2 text-xs hover:text-ink"><Icon aria-hidden className="h-4 w-4 text-muted" />{name}</Link>
            <StatusBadge status={query.isError ? "unavailable" : query.isSuccess ? "connected" : "connecting"} />
          </div>)}
        </div>
        <p className="mt-2 text-[11px] leading-4 text-muted">{t("Connection status reflects the latest API request.")}</p>
      </OverviewPanel>
    </div>
    <p className="mt-3 text-[11px] leading-4 text-muted/70">{t("Exploring cyclic learning, autonomous research, and statistically grounded validation.")}</p>
  </div>;
}
