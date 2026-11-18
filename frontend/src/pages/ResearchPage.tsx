import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../features/api";
import { PageHeader } from "../components/shared/PageHeader";
import { Panel } from "../components/shared/Panel";
import { PanelDiscovery, type PanelEvidence } from "./PanelDiscovery";
import { useTranslation } from "react-i18next";

type Run = { run_id: string; factors: number | null; status: string };
type Factor = { expression: string; observations: number; distinct_dates: number; symbols: string[]; years: string[]; decision_mse: number | null; mean_baseline_mse: number | null; status: string; availability: string };
type Scores = { scheduled: number; scored: number; squared_error?: number; zero_error?: number; mean_error?: number };
type Followup = { symbol: string; expression: string; first_date: string; all_periods: Scores; first_6: Scores; next_6: Scores };
type Detail = { run_id: string; status: string; factors: Factor[]; limitation: string; followup?: { scope: string; cards: Followup[] } | null; artifacts: Record<string, { sha256: string; content: unknown }>; panel_discovery?: PanelEvidence };
const metric = (value: number | null | undefined) => value == null ? "Unavailable" : (value * 10000).toFixed(3);

export function ResearchPage() {
  const { t } = useTranslation();
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const [expression, setExpression] = useState("");
  const runs = useQuery({ queryKey: ["research-runs"], queryFn: () => getJson<Run[]>("/api/research/runs") });
  const runId = selected || runs.data?.[0]?.run_id;
  const detail = useQuery({ queryKey: ["research-run", runId], queryFn: () => getJson<Detail>(`/api/research/runs/${encodeURIComponent(runId!)}`), enabled: Boolean(runId) });
  const factors = detail.data?.factors.filter(f => `${f.expression} ${f.symbols?.join(" ")}`.toLowerCase().includes(search.toLowerCase())) ?? [];
  const active = factors.find(f => f.expression === expression) ?? factors[0];
  const tracked = detail.data?.followup?.cards.filter(card => card.expression === active?.expression) ?? [];
  return <>
    <PageHeader eyebrow={t("Research / Factor library")} title={t("Factor research")} description={t("Inspect formulas and the evidence available at each recorded research run.")} />
    {runs.isPending && <p role="status">{t("Loading research runs…")}</p>}
    {runs.isError && <p role="alert">{runs.error.message}</p>}
    {runs.data?.length === 0 && <Panel title={t("No research artifacts available")}><p className="text-sm text-muted">{t("No completed factor libraries are available in this workspace.")}</p></Panel>}
    {Boolean(runs.data?.length) && <div className="mb-5 flex flex-wrap items-end gap-4">
      <label className="text-sm">{t("Research run")}<select aria-label={t("Research run")} className="mt-1 block rounded border border-line bg-surface p-2" value={runId} onChange={e => { setSelected(e.target.value); setExpression(""); }}>{runs.data!.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id} · {r.factors ?? "?"} candidates · {r.status}</option>)}</select></label>
      {!detail.data?.panel_discovery && <label className="min-w-64 flex-1 text-sm">{t("Search formulas or symbols")}<input className="mt-1 block w-full rounded border border-line bg-surface p-2" value={search} onChange={e => setSearch(e.target.value)} placeholder={t("Formula or symbol")} /></label>}
    </div>}
    {runId && detail.isPending && <p role="status">{t("Loading factor evidence…")}</p>}
    {detail.isError && <p role="alert">{detail.error.message}</p>}
    {detail.data && <>
      <div className="mb-5 rounded border border-amber-500/30 bg-amber-500/5 p-4 text-sm"><strong>{t("Exploratory evidence")}</strong><p className="mt-1 text-muted">{detail.data.limitation}</p></div>
      {detail.data.panel_discovery ? <PanelDiscovery key={runId} data={detail.data.panel_discovery} /> : <>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Panel title={t("Formula library")} description={`${factors.length} matching candidates`}>
          <div className="max-h-[640px] overflow-auto">{factors.length === 0 && <p className="text-sm text-muted">{t("No matching formulas.")}</p>}{factors.map(f => <button key={f.expression} onClick={() => setExpression(f.expression)} aria-pressed={active?.expression === f.expression} className={`mb-2 block w-full rounded border p-3 text-left ${active?.expression === f.expression ? "border-accent bg-elevated" : "border-line hover:bg-elevated/50"}`}><code className="break-all text-xs">{f.expression}</code><span className="mt-2 block text-xs text-muted">{f.symbols?.join(", ")} · {f.distinct_dates} decision dates</span></button>)}</div>
        </Panel>
        {active && <Panel title={t("Candidate evidence")} description={t("Scores cover selected decisions and may overlap. They are not an independent forward test.")}>
          <code className="block break-all rounded bg-elevated p-3 text-xs">{active.expression}</code>
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
            <div><dt className="text-muted">{t("Decision MSE × 10,000")}</dt><dd className="mt-1 text-xl tabular-nums">{metric(active.decision_mse)}</dd></div>
            <div><dt className="text-muted">{t("Mean baseline MSE × 10,000")}</dt><dd className="mt-1 text-xl tabular-nums">{metric(active.mean_baseline_mse)}</dd></div>
            <div><dt className="text-muted">{t("Distinct decision dates")}</dt><dd>{active.distinct_dates}</dd></div><div><dt className="text-muted">{t("Observation records")}</dt><dd>{active.observations}</dd></div>
            <div><dt className="text-muted">{t("Symbols")}</dt><dd>{active.symbols?.join(", ")}</dd></div><div><dt className="text-muted">{t("Years")}</dt><dd>{active.years?.join(", ")}</dd></div>
          </dl><p className="mt-5 text-sm">{active.status}</p><p className="mt-2 text-xs text-muted">{active.availability}</p>
          <h3 className="mt-6 text-sm font-semibold">{t("Performance after selection")}</h3>
          {tracked.length === 0 ? <p className="mt-2 text-sm text-muted">{t("No follow-up evidence recorded for this formula.")}</p> : <>
            <p className="mt-2 text-xs text-muted">{detail.data.followup?.scope}</p>
            {tracked.map(card => <div key={card.symbol} className="mt-4 overflow-x-auto"><p className="mb-2 text-xs">{card.symbol} · first selected {card.first_date}</p><table className="w-full text-left text-xs"><caption className="sr-only">Forward MSE comparison for {card.symbol}, multiplied by 10,000</caption><thead><tr className="border-b border-line"><th className="py-2">{t("Period")}</th><th>{t("Scored")}</th><th>{t("Factor")}</th><th>{t("Zero")}</th><th>{t("Mean")}</th></tr></thead><tbody>{([["First 6", card.first_6], ["Next 6", card.next_6], ["All follow-up", card.all_periods]] as [string, Scores][]).map(([label, scores]) => <tr key={label} className="border-b border-line/50"><th className="py-2 font-normal">{label}</th><td>{scores.scored}/{scores.scheduled}</td><td>{metric(scores.squared_error)}</td><td>{metric(scores.zero_error)}</td><td>{metric(scores.mean_error)}</td></tr>)}</tbody></table><p className="mt-2 text-xs text-muted">{t("MSE × 10,000. Lower is better. Historical follow-up is not prospective certification.")}</p></div>)}
          </>}
        </Panel>}
      </div>
      <Panel title={t("Recorded artifacts")} className="mt-5" description="Content fingerprints identify the files being viewed; they do not certify their scientific validity.">{Object.entries(detail.data.artifacts).map(([name, artifact]) => <details key={name} className="border-b border-line py-3"><summary className="cursor-pointer text-sm">{name}<span className="ml-3 font-mono text-xs text-muted">{artifact.sha256.slice(0, 16)}</span></summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(artifact.content, null, 2)}</pre></details>)}</Panel>
      </>}
    </>}
  </>;
}
