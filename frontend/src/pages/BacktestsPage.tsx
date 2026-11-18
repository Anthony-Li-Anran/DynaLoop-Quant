import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MetricCard } from "../components/shared/MetricCard";
import { PageHeader } from "../components/shared/PageHeader";
import { Panel } from "../components/shared/Panel";
import { EmptyState, LoadingState } from "../components/shared/States";
import { Button } from "../components/ui/Button";
import { Drawer } from "../components/ui/Drawer";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import {
  api,
  type BacktestResult,
  type BacktestRunResponse,
} from "../features/api";
import { ReplayPlayer } from "../features/backtests/ReplayPlayer";
import { RunSetup } from "../features/backtests/RunSetup";
import { useTranslation } from "react-i18next";

type BacktestView = "preview" | "setup";

const views = [
  { value: "preview", label: "Preview" },
  { value: "setup", label: "Setup" },
] as const;

function yuan(value: number | null | undefined): string {
  return typeof value === "number"
    ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "—";
}

function percent(value: number | null | undefined): string {
  return typeof value === "number" ? `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%` : "—";
}

export function BacktestsPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [activeView, setActiveView] = useState<BacktestView>(
    searchParams.get("view") === "setup" ? "setup" : "preview",
  );
  const [freshRun, setFreshRun] = useState<BacktestRunResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const results = useQuery({
    queryKey: ["backtests", "results"],
    queryFn: api.backtestResults,
  });
  const orderedResults = [...(results.data ?? [])].sort((left, right) =>
    (right.created_at ?? "").localeCompare(left.created_at ?? ""),
  );
  const activeRunId = selectedRunId ?? orderedResults[0]?.run_id ?? null;
  const detail = useQuery({
    queryKey: ["backtests", "result", activeRunId],
    queryFn: () => api.backtestResult(activeRunId as string),
    enabled: Boolean(activeRunId) && !freshRun,
  });

  const result: BacktestResult | undefined = freshRun?.result ?? detail.data?.result;
  // Pane declarations are view metadata stored alongside the run, never part
  // of the deterministic engine result (AGENTS.md section 1.11).
  const panes = freshRun?.panes ?? detail.data?.setup?.panes ?? [];
  const savedVisible = (freshRun?.view_config ?? detail.data?.setup?.view_config)?.visible_panes ?? [];
  const savedVisibleKey = savedVisible.join("|");
  const [visiblePanes, setVisiblePanes] = useState<string[]>([]);

  useEffect(() => {
    setVisiblePanes(savedVisibleKey ? savedVisibleKey.split("|") : []);
  }, [activeRunId, savedVisibleKey]);

  const symbol = result?.spec.symbols[0] ?? "—";
  const metadata = (result?.resolved_config.metadata ?? {}) as Record<string, unknown>;
  const strategyLabel = String(metadata.strategy_class ?? "—");
  const sourceLabel = String(metadata.source_key ?? "—");

  function handleRun(response: BacktestRunResponse) {
    setFreshRun(response);
    setSelectedRunId(response.run_id);
    setActiveView("preview");
    void queryClient.invalidateQueries({ queryKey: ["backtests", "results"] });
  }

  function togglePane(paneId: string) {
    const next = visiblePanes.includes(paneId)
      ? visiblePanes.filter((id) => id !== paneId)
      : [...visiblePanes, paneId];
    setVisiblePanes(next);
    // Persisting a checkbox only updates the stored view config; the engine
    // result and its resolved spec stay untouched.
    if (activeRunId) void api.saveViewConfig(activeRunId, next).catch(() => undefined);
  }

  function chooseRun(runId: string) {
    setFreshRun(null);
    setSelectedRunId(runId);
    setActiveView("preview");
    setHistoryOpen(false);
  }

  return (
    <>
      <PageHeader
        eyebrow={t("Research workspace / Validation & Backtesting")}
        title={t("Backtests")}
        description={t("Pick a data source and instrument, replay the tape bar by bar, and inspect every trade.")}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button size="sm" variant="secondary" onClick={() => setHistoryOpen(true)}>
              <History className="h-4 w-4" />
              {t("Recent runs")}
            </Button>
            <SegmentedControl
              label={t("Backtest workspace view")}
              value={activeView}
              options={views.map((view) => ({ ...view, label: t(view.label) }))}
              onChange={setActiveView}
            />
          </div>
        }
      />

      {activeView === "setup" ? (
        <div className="mx-auto w-full max-w-6xl">
          <RunSetup onRun={handleRun} />
        </div>
      ) : (
        <div className="space-y-4">
          {results.isLoading || (activeRunId && detail.isLoading && !freshRun) ? (
            <LoadingState title={t("Loading replay tape…")} />
          ) : !result ? (
            <EmptyState
              title={t("No replay yet")}
              description={t("Set up a backtest: choose a source, an instrument, a window and a strategy.")}
              action={
                <Button variant="primary" onClick={() => setActiveView("setup")}>
                  <Settings2 className="h-4 w-4" />
                  {t("Open setup")}
                </Button>
              }
            />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                <span className="font-medium text-ink">{freshRun?.label ?? detail.data?.label ?? `${symbol} · ${strategyLabel}`}</span>
                <span>{t("Source:")} <span className="font-mono text-ink">{sourceLabel}</span></span>
                <span>{t("Symbol:")} <span className="font-mono text-ink">{symbol}</span></span>
                <span>{t("Strategy:")} <span className="font-mono text-ink">{strategyLabel}</span></span>
                <span>
                  {t("Window:")} <span className="font-mono text-ink">{result.spec.realized_window.start}</span>
                  {" → "}
                  <span className="font-mono text-ink">{result.spec.realized_window.end}</span>
                </span>
              </div>

              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
                <MetricCard label="Final equity (CNY)" value={yuan(result.metrics.final_equity)} note={`Start ${yuan(result.metrics.initial_cash)}`} />
                <MetricCard label={t("Total return")} value={percent(result.metrics.total_return)} />
                <MetricCard label={t("Max drawdown")} value={percent(result.metrics.max_drawdown)} />
                <MetricCard label={t("Executed trades")} value={result.metrics.fill_count} note={`${result.metrics.rejected_count} rejected`} />
                <MetricCard label={t("Bars")} value={result.spec.bar_count} note={t("Ordered timestamps")} />
              </div>

              <Panel title={t("Replay")}>
                <ReplayPlayer
                  result={result}
                  symbol={symbol}
                  onOpenDetails={() => setDetailsOpen(true)}
                  panes={panes}
                  visiblePanes={visiblePanes}
                  onTogglePane={togglePane}
                />
              </Panel>
            </>
          )}
        </div>
      )}

      <Drawer
        open={historyOpen}
        title={t("Recent runs")}
        description={t("Stored results can be replayed without re-running the engine.")}
        onClose={() => setHistoryOpen(false)}
      >
        {orderedResults.length === 0 ? (
          <EmptyState title={t("No stored runs")} description={t("Run a backtest from Setup to create one.")} />
        ) : (
          <div className="space-y-2">
            {orderedResults.map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => chooseRun(run.run_id)}
                className={`w-full rounded-md border px-3 py-3 text-left transition-colors hover:border-muted ${
                  run.run_id === activeRunId ? "border-accent/70 bg-elevated/40" : "border-line bg-elevated/10"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-ink">
                    {run.label ?? `${run.symbol ?? "Run"} · ${run.strategy_class ?? "strategy"}`}
                  </span>
                  <span className="shrink-0 font-mono text-xs text-ink">{percent(run.total_return)}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-muted">
                  <span className="font-mono">{run.symbol ?? "—"}</span>
                  <span>{run.strategy_class ?? "—"}</span>
                  <span>{run.bar_count ?? 0} bars</span>
                  <span>{run.fill_count ?? 0} trades</span>
                </div>
                <div className="mt-1 font-mono text-[10px] text-muted">
                  {run.window?.start ?? "—"} → {run.window?.end ?? "—"}
                </div>
              </button>
            ))}
          </div>
        )}
      </Drawer>

      <Drawer
        open={detailsOpen}
        title={t("Run details")}
        description={t("Resolved configuration, runtime spec and the complete fill ledger.")}
        onClose={() => setDetailsOpen(false)}
        width="lg"
      >
        {result && (
          <div className="space-y-5">
            {result.warnings.length > 0 && (
              <div className="rounded-md border border-accent/40 bg-accent/5 px-3 py-2 text-xs text-accent">
                {result.warnings.map((warning) => <p key={warning} className="mb-1 last:mb-0">{warning}</p>)}
              </div>
            )}
            <div className="scroll-panel" style={{ maxHeight: "14rem" }}>
              <table className="data-table w-full text-xs">
                <thead>
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-muted">{t("Bar")}</th>
                    <th className="px-3 py-2 text-left font-medium text-muted">{t("Trading date")}</th>
                    <th className="px-3 py-2 text-left font-medium text-muted">{t("Side")}</th>
                    <th className="px-3 py-2 text-left font-medium text-muted">{t("Status")}</th>
                    <th className="px-3 py-2 text-right font-medium text-muted">Quantity (shares)</th>
                    <th className="px-3 py-2 text-right font-medium text-muted">Fill price (CNY)</th>
                    <th className="px-3 py-2 text-right font-medium text-muted">Fee (CNY)</th>
                  </tr>
                </thead>
                <tbody>
                  {result.fills.map((fill) => (
                    <tr key={fill.fill_id} className="border-t border-line/60">
                      <td className="px-3 py-1.5 font-mono text-muted">{fill.bar_index + 1}</td>
                      <td className="px-3 py-1.5 font-mono text-muted">{fill.timestamp}</td>
                      <td className="px-3 py-1.5" style={{ color: fill.quantity > 0 ? "#f87171" : "#4ade80" }}>
                        {fill.quantity > 0 ? "Buy" : "Sell"}
                      </td>
                      <td className="px-3 py-1.5 text-muted">{fill.status}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-ink">{Math.abs(fill.quantity).toLocaleString("zh-CN")}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-ink">{yuan(fill.price)}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-ink">{yuan(fill.commission)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{t("Resolved config")}</h3>
              <pre className="scroll-panel overflow-auto p-3 font-mono text-[11px] leading-5 text-ink">
                {JSON.stringify(result.resolved_config, null, 2)}
              </pre>
            </div>
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{t("Runtime spec")}</h3>
              <pre className="scroll-panel overflow-auto p-3 font-mono text-[11px] leading-5 text-ink">
                {JSON.stringify(result.spec, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
}
