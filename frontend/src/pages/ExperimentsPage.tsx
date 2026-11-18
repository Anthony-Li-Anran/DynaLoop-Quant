import { ResultPanel } from "../features/experiments/components/ResultPanel";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DataTable, type Column } from "../components/shared/DataTable";
import { DetailPanel, MetadataList } from "../components/shared/DetailPanel";
import { TimeDisplay } from "../components/shared/Formatting";
import { PageHeader, SectionHeader } from "../components/shared/PageHeader";
import { QueryState, ErrorState } from "../components/shared/States";
import { StatusBadge } from "../components/shared/StatusBadge";
import { api, type Experiment, type ExperimentRun } from "../features/api";
import { useTranslation } from "react-i18next";

export function ExperimentsPage() {
  const { t } = useTranslation();
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: api.experiments });
  const [selectedExperimentId, setSelectedExperimentId] = useState<string>();
  const [selectedRunId, setSelectedRunId] = useState<string>();
  const activeExperimentId = selectedExperimentId ?? experiments.data?.[0]?.experiment_id;
  const activeExperiment = experiments.data?.find((item) => item.experiment_id === activeExperimentId);
  const runs = useQuery({
    queryKey: ["experiments", activeExperimentId, "runs"],
    queryFn: () => api.runs(activeExperimentId!),
    enabled: Boolean(activeExperimentId),
  });
  const activeRunId = selectedRunId ?? runs.data?.[0]?.run_id;
  const run = useQuery({
    queryKey: ["runs", activeRunId],
    queryFn: () => api.run(activeRunId!),
    enabled: Boolean(activeRunId),
  });
  const result = useQuery({
    queryKey: ["runs", activeRunId, "result"],
    queryFn: () => api.result(activeRunId!),
    enabled: Boolean(activeRunId),
  });

  const experimentColumns: Column<Experiment>[] = [
    { key: "name", header: "Experiment", render: (item) => <span className="font-medium text-ink">{item.name}</span> },
    { key: "purpose", header: "Research purpose", render: (item) => item.research_purpose ?? <span className="text-muted">—</span> },
    { key: "config", header: "Configuration", render: (item) => item.configuration_version ? <span className="font-mono text-xs">{item.configuration_version}</span> : <span className="text-muted">—</span> },
  ];
  const runColumns: Column<ExperimentRun>[] = [
    { key: "run", header: "Run", render: (item) => <span className="font-mono text-xs text-ink">{item.run_id}</span> },
    { key: "status", header: "Status", render: (item) => <StatusBadge status={item.status} /> },
    { key: "config", header: "Config version", render: (item) => item.configuration_version ?? <span className="text-muted">{t("Snapshot only")}</span> },
    { key: "created", header: "Created", render: (item) => <TimeDisplay value={item.created_at} /> },
  ];

  return (
    <>
      <PageHeader eyebrow={t("Experiments / History")} title={t("Experiments")} description={t("Inspect recorded configurations, run lifecycle states, results, metrics, and external artifact references.")} />
      <section>
        <SectionHeader title={t("Experiment registry")} description="Definitions are displayed as recorded; this workspace does not execute or schedule runs." />
        <QueryState query={experiments} emptyTitle={t("No experiments recorded")}>
          {(rows) => <DataTable rows={rows} columns={experimentColumns} getRowKey={(row) => row.experiment_id} onRowClick={(row) => { setSelectedExperimentId(row.experiment_id); setSelectedRunId(undefined); }} />}
        </QueryState>
      </section>

      {activeExperiment && (
        <section className="mt-6 grid gap-4 xl:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
          <DetailPanel title={activeExperiment.name} description={activeExperiment.experiment_id}>
            <MetadataList
              items={[
                { label: "Description", value: activeExperiment.description },
                { label: t("Research purpose"), value: activeExperiment.research_purpose },
                { label: t("Configuration reference"), value: activeExperiment.configuration_reference },
                { label: t("Configuration version"), value: activeExperiment.configuration_version },
              ]}
            />
          </DetailPanel>
          <DetailPanel title={t("Run history")} description={t("Select a run to inspect its immutable configuration snapshot and outcome.")}>
            <QueryState query={runs} emptyTitle={t("No runs for this experiment")}>
              {(rows) => <DataTable rows={rows} columns={runColumns} getRowKey={(row) => row.run_id} onRowClick={(row) => setSelectedRunId(row.run_id)} />}
            </QueryState>
          </DetailPanel>
        </section>
      )}

      {run.data && activeRunId && (
        <section className="mt-6 grid gap-4 xl:grid-cols-2">
          <DetailPanel title={t("Run details")} description={run.data.run_id}>
            <MetadataList
              items={[
                { label: "Status", value: <StatusBadge status={run.data.status} /> },
                { label: "Created", value: <TimeDisplay value={run.data.created_at} /> },
                { label: "Started", value: <TimeDisplay value={run.data.started_at} /> },
                { label: "Finished", value: <TimeDisplay value={run.data.finished_at} /> },
                { label: t("Configuration version"), value: run.data.configuration_version },
                { label: "Failure", value: run.data.failure_message },
              ]}
            />
            <div className="mt-5">
              <p className="mb-2 text-xs font-medium text-muted">{t("Configuration snapshot")}</p>
              <pre className="max-h-72 overflow-auto rounded-md border border-line bg-canvas p-4 font-mono text-xs leading-5 text-ink">
                {formatConfiguration(run.data.configuration_snapshot)}
              </pre>
            </div>
          </DetailPanel>
          <ResultPanel query={result} />
        </section>
      )}
      {activeRunId && run.error && (
        <ErrorState title={t("Unable to load run")} description={run.error.message} />
      )}
    </>
  );
}

function formatConfiguration(snapshot: string): string {
  try {
    return JSON.stringify(JSON.parse(snapshot) as unknown, null, 2);
  } catch {
    return snapshot;
  }
}
