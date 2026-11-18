import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Gauge, Play, Repeat } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { DataTable, type Column } from "../components/shared/DataTable";
import { TimeDisplay } from "../components/shared/Formatting";
import { OverviewMetric, OverviewPanel } from "../components/shared/OverviewPanel";
import { QueryState } from "../components/shared/States";
import { Button } from "../components/ui/Button";
import { SelectField } from "../components/ui/SelectField";
import { api, type LoopRunDetail, type LoopRunSummary } from "../features/api";
import { useTranslation } from "react-i18next";

const SYNTHETIC = "synthetic";

const inputClass =
  "min-h-10 w-full rounded-md border border-line bg-canvas px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

function NumberField({ label, value, onChange, step }: {
  label: string; value: number; onChange: (value: number) => void; step?: number;
}) {
  return (
    <label className="block">
      <span className="text-[13px] font-medium text-ink">{label}</span>
      <input
        className={inputClass}
        type="number"
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

type RoundRow = {
  round_index: number;
  reliability: number | null;
  policy_version: number | null;
  run_id: string;
  stages: { stage: string; status: string }[];
};

const roundColumns: Column<RoundRow>[] = [
  {
    key: "round",
    header: "Round",
    render: (row) => <span className="font-medium">#{row.round_index + 1}</span>,
  },
  {
    key: "stages",
    header: "Stages",
    render: (row) => (
      <div className="flex flex-wrap gap-1">
        {row.stages.map((stage) => (
          <span
            key={stage.stage}
            title={stage.stage}
            className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
              stage.status === "completed"
                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "bg-rose-500/10 text-rose-600 dark:text-rose-400"
            }`}
          >
            {stage.stage.replace(/_/g, " ")}
          </span>
        ))}
      </div>
    ),
  },
  {
    key: "reliability",
    header: "Reliability",
    render: (row) => (row.reliability === null ? "—" : row.reliability.toFixed(3)),
  },
  {
    key: "policy",
    header: "Policy",
    render: (row) => (row.policy_version === null ? "—" : `v${row.policy_version}`),
  },
  {
    key: "run",
    header: "Experiment run",
    render: (row) => (
      <Link className="hover:text-blue-400" to="/experiments">
        {row.run_id.slice(0, 12)}
      </Link>
    ),
  },
];

function roundRows(detail: LoopRunDetail): RoundRow[] {
  return detail.result.rounds.map((round) => {
    const finalSpec = (round.spec["final"] ?? {}) as Record<string, unknown>;
    return {
      round_index: round.round_index,
      reliability:
        typeof finalSpec["reliability"] === "number" ? finalSpec["reliability"] : null,
      policy_version:
        typeof finalSpec["policy_version"] === "number" ? finalSpec["policy_version"] : null,
      run_id: round.run_id,
      stages: round.stages.map((stage) => ({ stage: stage.stage, status: stage.status })),
    };
  });
}

export function LoopPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const sources = useQuery({ queryKey: ["backtests", "sources"], queryFn: api.backtestSources });
  const runs = useQuery({ queryKey: ["loop", "runs"], queryFn: api.loopRuns });

  const [origin, setOrigin] = useState(SYNTHETIC);
  const [symbol, setSymbol] = useState("TEST");
  const [start, setStart] = useState("2024-01-01");
  const [end, setEnd] = useState("2024-02-10");
  const [seed, setSeed] = useState(7);
  const [rounds, setRounds] = useState(3);
  const [groupSize, setGroupSize] = useState(6);
  const [generator, setGenerator] = useState("template");
  const [biasMagnitude, setBiasMagnitude] = useState(0);
  const [biasMode, setBiasMode] = useState("additive");
  const [experimentId, setExperimentId] = useState("dynaloop-loop");
  const [selected, setSelected] = useState<string | null>(null);

  const sourceList = (sources.data ?? []).filter((item) => item.compatible);
  const activeSource = sourceList.find((item) => item.key === origin);

  // When the data origin changes, sync symbol and window to the selected source
  // (mirrors the Backtests RunSetup page). Synthetic demo keeps its own defaults;
  // a real source gets its first declared symbol so the backend does not try to
  // fetch the literal "TEST". Only re-sync on an actual origin switch, never
  // while the user is editing the fields.
  const lastOrigin = useRef<string | null>(null);
  useEffect(() => {
    const changed = lastOrigin.current !== origin;
    lastOrigin.current = origin;
    if (!changed) return;
    if (origin === SYNTHETIC) {
      setSymbol("TEST");
      setStart("2024-01-01");
      setEnd("2024-02-10");
      return;
    }
    if (!activeSource) return;
    if (activeSource.symbols.length > 0) {
      setSymbol(activeSource.symbols[0].symbol);
    }
    setStart(activeSource.default_start || "2024-01-02");
    setEnd(activeSource.default_end || "2024-06-28");
  }, [origin, activeSource]);

  const runLoop = useMutation({
    mutationFn: api.runLoop,
    onSuccess: (detail) => {
      setSelected(detail.fingerprint);
      void queryClient.invalidateQueries({ queryKey: ["loop", "runs"] });
    },
  });

  const detail = useQuery({
    queryKey: ["loop", "runs", selected],
    queryFn: () => api.loopRun(selected as string),
    enabled: selected !== null,
  });

  const weights = detail.data?.result.final_policy?.weights ?? null;
  const topWeights = weights
    ? Object.entries(weights).sort((a, b) => b[1] - a[1]).slice(0, 8)
    : [];

  const summaryColumns: Column<LoopRunSummary>[] = [
    {
      key: "fingerprint",
      header: "Fingerprint",
      render: (row) => <span className="font-mono text-xs">{row.fingerprint.slice(0, 12)}</span>,
    },
    { key: "origin", header: "Data origin", render: (row) => row.origin },
    { key: "rounds", header: "Rounds", render: (row) => row.round_count },
    {
      key: "reliability",
      header: "Reliability",
      render: (row) => (row.final_reliability === null ? "—" : row.final_reliability.toFixed(3)),
    },
    { key: "created", header: "Created", render: (row) => <TimeDisplay value={row.created_at} /> },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("Closed loop")}
        title={t("Loop runs")}
        description="Drive the six-stage exploration loop over one frozen window: sample candidate factors, validate on the real engine, estimate through the Sleep proxy, update the policy, and record every round. Same seed and configuration reproduce the same fingerprint."
      />

      <OverviewPanel title={t("Run configuration")}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectField
            label={t("Data origin")}
            value={origin}
            onChange={setOrigin}
            options={[
              { value: SYNTHETIC, label: t("Synthetic demo bars (labeled)") },
              ...sourceList.map((source) => ({ value: source.key, label: source.name })),
            ]}
          />
          <label className="block">
            <span className="text-[13px] font-medium text-ink">{t("Symbol")}</span>
            <input className={inputClass} value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-[13px] font-medium text-ink">{t("Window start")}</span>
            <input className={inputClass} value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-[13px] font-medium text-ink">{t("Window end")}</span>
            <input className={inputClass} value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <NumberField label={t("Seed")} value={seed} onChange={setSeed} />
          <NumberField label={t("Rounds")} value={rounds} onChange={setRounds} />
          <NumberField label={t("Group size")} value={groupSize} onChange={setGroupSize} />
          <SelectField
            label={t("Generator")}
            value={generator}
            onChange={setGenerator}
            options={[
              { value: "template", label: t("Template (Alpha158-style)") },
              { value: "grammar", label: t("Grammar (typed trees)") },
            ]}
          />
          <NumberField label={t("Injected bias")} value={biasMagnitude} onChange={setBiasMagnitude} step={0.01} />
          <SelectField
            label={t("Bias mode")}
            value={biasMode}
            onChange={setBiasMode}
            options={[
              { value: "additive", label: "Additive" },
              { value: "multiplicative", label: "Multiplicative" },
            ]}
          />
          <label className="block sm:col-span-2">
            <span className="text-[13px] font-medium text-ink">{t("Experiment ID")}</span>
            <input className={inputClass} value={experimentId} onChange={(e) => setExperimentId(e.target.value)} />
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button
            variant="primary"
            disabled={runLoop.isPending || (origin !== SYNTHETIC && !activeSource)}
            onClick={() =>
              runLoop.mutate({
                source_key: origin === SYNTHETIC ? null : origin,
                symbol,
                start,
                end,
                seed,
                rounds,
                group_size: groupSize,
                generator,
                bias_magnitude: biasMagnitude,
                bias_mode: biasMode,
                experiment_id: experimentId,
              })
            }
          >
            <Play className="h-4 w-4" />
            {runLoop.isPending ? "Running…" : "Run loop"}
          </Button>
          {origin !== SYNTHETIC && !activeSource && (
            <span className="text-xs text-amber-600 dark:text-amber-400">
              {t("Selected source has no usable capability yet.")}
            </span>
          )}
          {runLoop.isError && (
            <span className="text-xs text-rose-600 dark:text-rose-400">
              {(runLoop.error as Error).message}
            </span>
          )}
        </div>
      </OverviewPanel>

      {detail.data && (
        <OverviewPanel title={`Run ${detail.data.fingerprint.slice(0, 12)}`} to="/experiments">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <OverviewMetric label={t("Rounds")} icon={Repeat} value={detail.data.round_count} note="rounds" />
            <OverviewMetric
              label={t("Final reliability")}
              icon={Gauge}
              value={
                detail.data.final_reliability === null
                  ? undefined
                  : Number(detail.data.final_reliability.toFixed(3))
              }
              note={t("descriptive, no guarantee")}
            />
            <OverviewMetric
              label={t("Policy version")}
              icon={Repeat}
              value={detail.data.result.final_policy?.version}
              note={t("final policy")}
            />
            <OverviewMetric
              label={t("Experiment runs")}
              icon={Repeat}
              value={detail.data.run_ids.length}
              note="persisted"
            />
          </div>
          <div className="mt-4">
            <DataTable
              rows={roundRows(detail.data)}
              columns={roundColumns}
              getRowKey={(row) => String(row.round_index)}
              emptyTitle={t("No rounds")}
            />
          </div>
          {topWeights.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-semibold">Top exploration weights (final policy)</h3>
              <div className="mt-2 flex flex-wrap gap-2">
                {topWeights.map(([key, value]) => (
                  <span key={key} className="rounded bg-elevated px-2 py-1 text-xs">
                    <span className="text-muted">{key}</span>{" "}
                    <span className="font-mono">{value.toFixed(3)}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
          <p className="mt-4 text-xs text-muted">
            Stage order: {(detail.data.result.spec.stage_order ?? []).join(" → ")} · Origin:{" "}
            {detail.data.origin} · Every round is persisted as an experiment run under{" "}
            <Link className="hover:text-blue-400" to="/experiments">
              {detail.data.experiment_id}
            </Link>
            .
          </p>
        </OverviewPanel>
      )}

      <section>
        <h2 className="section-title">{t("Stored loop runs")}</h2>
        <p className="mt-1 text-[13px] text-muted">
          Same seed and configuration reproduce the same fingerprint; re-running an identical setup
          refreshes the stored entry instead of duplicating it.
        </p>
        <div className="mt-3">
          <QueryState query={runs}>
            {(data) => (
              <DataTable
                rows={data}
                columns={summaryColumns}
                getRowKey={(row) => row.fingerprint}
                onRowClick={(row) => setSelected(row.fingerprint)}
                emptyTitle={t("No loop runs yet")}
                emptyDescription="Run the six-stage loop above; stored runs will appear here with their fingerprints."
              />
            )}
          </QueryState>
        </div>
      </section>
    </div>
  );
}

export default LoopPage;
