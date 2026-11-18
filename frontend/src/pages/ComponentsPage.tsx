import { SelectField } from "../components/ui/SelectField";
import { useCallback, useState } from "react";
import { BRAND } from "../app/brand";
import { PageHeader } from "../components/shared/PageHeader";
import { Panel } from "../components/shared/Panel";
import { MetricCard } from "../components/shared/MetricCard";
import { DataTable } from "../components/shared/DataTable";
import { MetadataList } from "../components/shared/DetailPanel";
import { StatusBadge } from "../components/shared/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/shared/States";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { useTranslation } from "react-i18next";

const specimens = [{ id: "example-01", name: "Example experiment", status: "completed" }, { id: "example-02", name: "Example dataset review", status: "pending" }];
export function ComponentsPage() {
  const { t } = useTranslation();
  const [exampleEncoding, setExampleEncoding] = useState("auto");
  const [selected, setSelected] = useState(specimens[0]);
  const [state, setState] = useState<"empty" | "loading" | "error">("empty");
  const [modalOpen, setModalOpen] = useState(false);
  const [workspaceView, setWorkspaceView] = useState<"dashboard" | "operations">("dashboard");
  const closeModal = useCallback(() => setModalOpen(false), []);
  return <>
    <PageHeader eyebrow={t("Design system / Components")} title={`${BRAND.name} UI`} description={t("Shared foundations and reusable components for a reproducible research workspace. All examples on this page are demonstration data.")} />
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title={t("01 / Foundations")} description={t("Neutral surfaces, restrained gold accents, semantic status colors.")}>
        <div className="grid grid-cols-3 gap-3">{["canvas", "surface", "elevated", "ink", "muted", "accent"].map(token => <div key={token}><div className="h-9 rounded border border-line" style={{ background: `rgb(var(--color-${token}))` }} /><code className="text-[11px] text-muted">{token}</code></div>)}</div>
        <p className="typography-sample-title">{t("Evidence before conclusions.")}</p>
        <p className="mt-2 text-xs leading-5 text-muted">Modern Research is the fixed workspace typography: Segoe UI with system and Chinese sans-serif fallbacks; Consolas with monospace fallbacks for identifiers and numbers.</p>
        <p className="mt-2 text-xs leading-5 text-muted">{t("Page titles: 26px / 1.4, weight 600, letter spacing 0.005em. Shared across every page.")}</p><p className="typography-sample-mono">{t("RankIC 0.0324 · Run 0018")}</p><p className="mt-2 font-mono text-xs text-muted">{t("Spacing 4 / 8 / 12 / 16 / 24 · radius 8")}</p>
      </Panel>
      <Panel title={t("CSV / Select field")} description={t("Shared labeled select used for encoding, separators and preview policies.")}><SelectField label={t("Example encoding")} value={exampleEncoding} onChange={setExampleEncoding} options={[{value:"auto",label:"Auto"},{value:"utf-8-sig",label: t("UTF-8")}]} /></Panel>
      <Panel title={t("02 / Controls")} description={t("Button: primary, secondary, ghost. Badge: semantic tone.")}>
        <div className="flex flex-wrap gap-2"><Button variant="primary" onClick={() => setSelected(specimens[0])}>{t("Select example 01")}</Button><Button onClick={() => setSelected(specimens[1])}>{t("Select example 02")}</Button><Button variant="ghost" disabled>{t("Disabled")}</Button></div>
        <p className="mt-3 text-xs text-muted" aria-live="polite">Selected: {selected.id}</p>
        <div className="mt-4 flex flex-wrap gap-2">{["pending", "running", "completed", "failed", "cancelled", "connected", "unavailable"].map(status => <StatusBadge key={status} status={status} />)}</div>
        <div className="mt-3"><Badge>{t("Read only")}</Badge></div>
      </Panel>
      <Panel title={t("03 / DataTable")} description={t("Typed columns and row keys. Selection is available with mouse or keyboard.")}>
        <DataTable rows={specimens} getRowKey={row => row.id} onRowClick={setSelected} columns={[
          { key: "name", header: "Record", render: row => row.name },
          { key: "status", header: "Status", render: row => <StatusBadge status={row.status} /> },
        ]} />
      </Panel>
      <Panel title={t("04 / Metrics & metadata")} description={t("MetricCard and MetadataList share the same spacing and numeric typography.")}>
        <div className="grid grid-cols-2 gap-3"><MetricCard label={t("Example count")} value={24} /><MetricCard label={t("Missing value")} value="—" /></div>
        <div className="mt-4"><MetadataList items={[{ label: t("Record ID"), value: <code>{selected.id}</code> }, { label: "Status", value: <StatusBadge status={selected.status} /> }]} /></div>
      </Panel>
      <Panel title={t("05 / Feedback")} description={t("Loading, empty, and error states have one shared implementation.")}>
        <div className="mb-3 flex gap-2">{(["empty", "loading", "error"] as const).map(value => <Button key={value} size="sm" variant={state === value ? "secondary" : "ghost"} aria-pressed={state === value} onClick={() => setState(value)}>{value}</Button>)}</div>
        {state === "loading" ? <LoadingState /> : state === "error" ? <ErrorState title={t("Example request failed")} description="Demonstration only; no network request was made." /> : <EmptyState title={t("No example records")} description={t("Explain the state clearly before offering a next action.")} />}
      </Panel>
      <Panel title={t("06 / Composition")} description={t("Three layers, with shared foundations underneath.")}>
        <MetadataList items={[{ label: "Primitives", value: "Button · Badge" }, { label: "Shared", value: "PageHeader · Panel · DataTable · MetricCard · StatusBadge · QueryState" }, { label: "Domain", value: "PartitionList · SnapshotView · QualityReportView · ResultPanel · RuntimeInfoPanel" }]} />
        <p className="mt-4 text-xs leading-5 text-muted">{t("Compose pages from existing components. Define colors and typography in styles/index.css. Keep domain data and fetching out of shared UI components.")}</p>
      </Panel>
      <Panel title={t("07 / ModalDialog")} description={t("Reusable modal card with Escape/backdrop dismissal, focus handling, and responsive layout.")}>
        <Button variant="secondary" onClick={() => setModalOpen(true)}>{t("Preview modal")}</Button>
        <ModalDialog
          open={modalOpen}
          title={t("Reusable modal card")}
          description={t("Use this shared surface for focused workflows such as data import.")}
          onClose={closeModal}
        >
          <div className="space-y-5">
            <p className="text-sm leading-6 text-muted">{t("A restrained surface, fine border, and warm accent line keep dialogs consistent with the workspace.")}</p>
            <div className="flex justify-end"><Button onClick={closeModal}>{t("Close preview")}</Button></div>
          </div>
        </ModalDialog>
      </Panel>
      <Panel title={t("08 / SegmentedControl")} description={t("A labeled, responsive choice for switching between peer workspace views.")}>
        <SegmentedControl
          label={t("Example workspace view")}
          value={workspaceView}
          options={[
            { value: "dashboard", label: "Dashboard" },
            { value: "operations", label: "Operations" },
          ]}
          onChange={setWorkspaceView}
        />
        <p className="mt-3 text-xs text-muted" aria-live="polite">
          Active view: {workspaceView}
        </p>
      </Panel>
    </div>
  </>;
}
