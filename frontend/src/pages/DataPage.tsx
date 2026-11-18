import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { DataTable, type Column } from "../components/shared/DataTable";
import { DetailPanel, MetadataList } from "../components/shared/DetailPanel";
import { TimeDisplay } from "../components/shared/Formatting";
import { MetricCard } from "../components/shared/MetricCard";
import { PageHeader } from "../components/shared/PageHeader";
import { Panel } from "../components/shared/Panel";
import { QueryState } from "../components/shared/States";
import { StatusBadge } from "../components/shared/StatusBadge";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { DataManagement } from "../features/data/components/DataManagement";
import { PartitionList } from "../features/data/components/PartitionList";
import { QualityReportView } from "../features/data/components/QualityReportView";
import { SnapshotView } from "../features/data/components/SnapshotView";
import { useTranslation } from "react-i18next";
import {
  api,
  type DataSource,
  type Dataset,
  type DatasetSnapshot,
  type DatasetVersion,
  type ProcessingLineage,
  type QualityReport,
} from "../features/api";

type DataView = "dashboard" | "operations";

const dataViews = [
  {
    value: "dashboard",
    label: "Dashboard",
  },
  {
    value: "operations",
    label: "Operations",
  },
] as const;

export function DataPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const sources = useQuery({ queryKey: ["data", "sources"], queryFn: api.sources });
  const datasets = useQuery({ queryKey: ["data", "datasets"], queryFn: api.datasets });
  const snapshots = useQuery({ queryKey: ["data", "snapshots"], queryFn: api.snapshots });
  const lineages = useQuery({ queryKey: ["data", "lineages"], queryFn: api.lineages });
  const quality = useQuery({ queryKey: ["data", "quality"], queryFn: api.qualityReports });
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>();
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string>();
  const [selectedQualityId, setSelectedQualityId] = useState<string>();
  const [activeView, setActiveView] = useState<DataView>(
    searchParams.get("view") === "operations" ? "operations" : "dashboard",
  );
  const [transitionDirection, setTransitionDirection] = useState<"forward" | "backward">("forward");
  const activeDatasetId = selectedDatasetId ?? datasets.data?.[0]?.dataset_id;
  const versions = useQuery({
    queryKey: ["data", "versions", activeDatasetId],
    queryFn: () => api.versions(activeDatasetId!),
    enabled: Boolean(activeDatasetId),
  });

  const sourceColumns: Column<DataSource>[] = [
    { key: "name", header: "Source", render: (row) => <span className="font-medium text-ink">{row.name}</span> },
    { key: "type", header: "Type", render: (row) => <span className="font-mono text-xs text-muted">{row.source_type}</span> },
    { key: "id", header: "Identifier", render: (row) => <span className="font-mono text-xs text-muted">{row.source_id}</span> },
  ];
  const datasetColumns: Column<Dataset>[] = [
    { key: "name", header: "Dataset", render: (row) => <span className="font-medium text-ink">{row.name}</span> },
    { key: "type", header: "Data type", render: (row) => row.data_type ?? <span className="text-muted">{t("Unspecified")}</span> },
    { key: "format", header: "Format", render: (row) => row.format_id ?? <span className="text-muted">{t("Unspecified")}</span> },
    { key: "sources", header: "Sources", render: (row) => row.source_ids.length || <span className="text-muted">—</span> },
  ];
  const versionColumns: Column<DatasetVersion>[] = [
    { key: "version", header: "Version", render: (row) => <span className="font-mono text-xs text-ink">{row.version_id}</span> },
    { key: "layer", header: "Layer", render: (row) => <StatusBadge status={row.data_layer} /> },
    { key: "created", header: "Created", render: (row) => <TimeDisplay value={row.created_at} /> },
    { key: "partitions", header: "Partitions", render: (row) => row.partitions.length },
    { key: "schema", header: "Schema", render: (row) => row.schema_id ? `${row.schema_id}@${row.schema_version}` : <span className="text-muted">—</span> },
  ];
  const snapshotColumns: Column<DatasetSnapshot>[] = [
    { key: "id", header: "Snapshot", render: (row) => <span className="font-mono text-xs text-ink">{row.snapshot_id}</span> },
    { key: "members", header: "Version members", render: (row) => row.members.length },
    { key: "partitions", header: "Mapped partitions", render: (row) => row.partition_sources.length },
  ];
  const lineageColumns: Column<ProcessingLineage>[] = [
    { key: "operation", header: "Operation", render: (row) => <span className="font-medium text-ink">{row.operation_name} <span className="font-mono text-xs text-muted">v{row.operation_version}</span></span> },
    { key: "inputs", header: "Inputs", render: (row) => row.input_versions.length },
    { key: "outputs", header: "Outputs", render: (row) => row.output_versions.length },
    { key: "executed", header: "Executed", render: (row) => <TimeDisplay value={row.executed_at} /> },
  ];
  const qualityColumns: Column<QualityReport>[] = [
    { key: "version", header: "Version", render: (row) => <span className="font-mono text-xs">{row.dataset_version.dataset_id}@{row.dataset_version.version_id}</span> },
    { key: "rules", header: "Rule set", render: (row) => `${row.rule_set_id} · ${row.rule_set_version}` },
    { key: "status", header: "Outcome", render: (row) => <StatusBadge status={row.status} /> },
    { key: "checked", header: "Checked", render: (row) => <TimeDisplay value={row.checked_at} /> },
  ];

  const activeDataset = datasets.data?.find((dataset) => dataset.dataset_id === activeDatasetId);
  const activeSnapshot = snapshots.data?.find((snapshot) => snapshot.snapshot_id === selectedSnapshotId);
  const activeQuality = quality.data?.find((report) => report.report_id === selectedQualityId);
  const qualityFailures = quality.data?.filter((report) => report.status === "failed").length ?? 0;
  const qualityWarnings = quality.data?.filter((report) => report.status === "warning").length ?? 0;

  function changeView(nextView: DataView) {
    if (nextView === activeView) return;
    setTransitionDirection(nextView === "operations" ? "forward" : "backward");
    setActiveView(nextView);
  }

  function metricCount(result: { data?: unknown[]; isLoading: boolean }): number | string {
    if (result.data) return result.data.length;
    return result.isLoading ? "—" : "Unavailable";
  }

  return (
    <>
      <PageHeader
        eyebrow={t("Research workspace / Data")}
        title={t("Data")}
        actions={
          <SegmentedControl
            label={t("Data workspace view")}
            value={activeView}
            options={dataViews}
            onChange={changeView}
          />
        }
      />

      <div
        key={activeView}
        role="region"
        aria-label={activeView === "dashboard" ? "Data dashboard" : "Data operations"}
        className={`data-workspace-panel data-workspace-panel--${transitionDirection}`}
      >
        {activeView === "dashboard" ? (
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label={t("Datasets")} value={metricCount(datasets)} note={t("Registered data collections")} />
              <MetricCard label={t("Data sources")} value={metricCount(sources)} note={t("Connected source records")} />
              <MetricCard label={t("Snapshots")} value={metricCount(snapshots)} note={t("Saved reproducible selections")} />
              <MetricCard
                label={t("Quality reports")}
                value={metricCount(quality)}
                note={quality.data ? `${qualityFailures} failed · ${qualityWarnings} warnings` : "Published data checks"}
              />
            </div>

            <Panel
              title={t("Dataset library")}
              description={t("Select a dataset to inspect its published versions and partitions.")}
            >
              <QueryState query={datasets} emptyTitle={t("No datasets yet")}>
                {(rows) => (
                  <DataTable
                    rows={rows}
                    columns={datasetColumns}
                    getRowKey={(row) => row.dataset_id}
                    onRowClick={(row) => setSelectedDatasetId(row.dataset_id)}
                    emptyDescription={t("Imported datasets will appear here.")}
                  />
                )}
              </QueryState>

              {activeDataset && (
                <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
                  <DetailPanel title={activeDataset.name} description={activeDataset.dataset_id}>
                    <MetadataList
                      items={[
                        { label: "Description", value: activeDataset.description },
                        { label: "Type", value: activeDataset.data_type },
                        { label: "Market", value: activeDataset.market },
                        { label: t("Time granularity"), value: activeDataset.time_granularity },
                        { label: "Format", value: activeDataset.format_id },
                        { label: t("Source IDs"), value: activeDataset.source_ids.join(", ") || "—" },
                      ]}
                    />
                  </DetailPanel>
                  <DetailPanel title={t("Published versions")} description={t("Only versions available for reproducible reads are shown.")}>
                    <QueryState query={versions} emptyTitle={t("No published versions")}>
                      {(rows) => (
                        <DataTable
                          rows={rows}
                          columns={versionColumns}
                          getRowKey={(row) => row.version_id}
                          emptyDescription={t("This dataset has no published versions.")}
                        />
                      )}
                    </QueryState>
                  </DetailPanel>
                </div>
              )}
              {activeDataset && versions.data?.length ? (
                <div className="mt-5">
                  <PartitionList versions={versions.data} />
                </div>
              ) : null}
            </Panel>

            <div className="grid gap-5 xl:grid-cols-2">
              <Panel title={t("Snapshots")} description={t("Explicit mappings to source versions and partitions.")}>
                <QueryState query={snapshots} emptyTitle={t("No snapshots saved")}>
                  {(rows) => (
                    <DataTable
                      rows={rows}
                      columns={snapshotColumns}
                      getRowKey={(row) => row.snapshot_id}
                      onRowClick={(row) => setSelectedSnapshotId(row.snapshot_id)}
                    />
                  )}
                </QueryState>
                {activeSnapshot && <SnapshotView activeSnapshot={activeSnapshot} />}
              </Panel>

              <Panel title={t("Data sources")} description="Registered source metadata; credentials are not managed here.">
                <QueryState query={sources} emptyTitle={t("No data sources registered")}>
                  {(rows) => <DataTable rows={rows} columns={sourceColumns} getRowKey={(row) => row.source_id} />}
                </QueryState>
              </Panel>

              <Panel title={t("Processing history")} description={t("Recorded operations and input/output version references.")}>
                <QueryState query={lineages} emptyTitle={t("No processing lineage recorded")}>
                  {(rows) => <DataTable rows={rows} columns={lineageColumns} getRowKey={(row) => row.lineage_id} />}
                </QueryState>
              </Panel>

              <Panel title={t("Quality reports")} description="Check outcomes; reports do not modify published data.">
                <QueryState query={quality} emptyTitle={t("No quality reports recorded")}>
                  {(rows) => (
                    <DataTable
                      rows={rows}
                      columns={qualityColumns}
                      getRowKey={(row) => row.report_id}
                      onRowClick={(row) => setSelectedQualityId(row.report_id)}
                    />
                  )}
                </QueryState>
                {activeQuality && <QualityReportView activeQuality={activeQuality} />}
              </Panel>
            </div>
          </div>
        ) : (
          <div className="mx-auto w-full max-w-6xl">
            <DataManagement />
          </div>
        )}
      </div>
    </>
  );
}
