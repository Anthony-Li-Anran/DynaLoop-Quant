import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../features/api";
import { PageHeader } from "../components/shared/PageHeader";
import { Panel } from "../components/shared/Panel";
import { useTranslation } from "react-i18next";

function shown(value: unknown): string {
  if (value === null || value === undefined) return "N/A";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "N/A";
  if (Array.isArray(value)) return value.map(shown).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function percent(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(2)}%`
    : "N/A";
}

function fixed(value: number | null | undefined, digits = 4): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "N/A";
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="rounded border border-line bg-elevated p-3">
    <p className="text-[11px] uppercase tracking-wide text-muted">{label}</p>
    <p className="mt-1 break-all text-lg tabular-nums">{value}</p>
    {note && <p className="mt-1 text-[11px] text-muted">{note}</p>}
  </div>;
}

export function EvidencePage() {
  const { t } = useTranslation();
  const [roundSelection, setRoundSelection] = useState("");
  const [demoSelection, setDemoSelection] = useState("");
  const rounds = useQuery({ queryKey: ["evidence-rounds"], queryFn: api.evidenceRounds });
  const executions = useQuery({ queryKey: ["evidence-executions"], queryFn: api.evidenceExecutions });
  const roundId = roundSelection || rounds.data?.[0]?.round_id;
  const detail = useQuery({
    queryKey: ["evidence-round", roundId],
    queryFn: () => api.evidenceRound(roundId!),
    enabled: Boolean(roundId),
  });
  const demoId = demoSelection || executions.data?.[0]?.demo_id;
  const demo = useQuery({
    queryKey: ["evidence-execution", demoId],
    queryFn: () => api.evidenceExecution(demoId!),
    enabled: Boolean(demoId),
  });
  const [walkSelection, setWalkSelection] = useState("");
  const walkRounds = useQuery({ queryKey: ["evidence-walkforward"], queryFn: api.walkforwardRounds });
  const walkId = walkSelection || walkRounds.data?.[0]?.directory;
  const walk = useQuery({
    queryKey: ["evidence-walkforward-detail", walkId],
    queryFn: () => api.walkforwardDetail(walkId!),
    enabled: Boolean(walkId),
  });

  return <>
    <PageHeader eyebrow={t("Research / Evidence")} title={t("Factor evidence")} description={t("Frozen certification records and execution demos, read without recomputation.")} />
    {rounds.isPending && <p role="status">{t("Loading certification rounds…")}</p>}
    {rounds.isError && <p role="alert">{rounds.error.message}</p>}
    {rounds.data?.length === 0 && <Panel title={t("No certification artifacts available")}><p className="text-sm text-muted">{t("No frozen certification rounds were found in the configured directory.")}</p></Panel>}
    {Boolean(rounds.data?.length) && <>
      <div className="mb-5 flex flex-wrap items-end gap-4">
        <label className="text-sm">"Certification round"
          <select aria-label={t("Certification round")} className="mt-1 block rounded border border-line bg-surface p-2" value={roundId} onChange={event => { setRoundSelection(event.target.value); }}>
            {rounds.data!.map(row => <option key={row.round_id} value={row.round_id}>{row.round_id} · {shown(row.status)} · {shown(row.family_p_value)}</option>)}
          </select>
        </label>
      </div>
      {detail.isPending && <p role="status">{t("Loading certification detail…")}</p>}
      {detail.isError && <p role="alert">{detail.error.message}</p>}
      {detail.data && <>
        <div className="metric-strip mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-5">
          <Metric label={t("Channel")} value={shown(detail.data.channel_label)} />
          <Metric label={t("Status")} value={shown(detail.data.status)} />
          <Metric label={t("Family p")} value={shown(detail.data.family_p_value)} note={t("Search-corrected decision field")} />
          <Metric label={t("Periods")} value={shown(detail.data.periods)} />
          <Metric label={t("Effective")} value={`${shown(detail.data.effective_count)} / ${shown(detail.data.candidate_count)}`} />
        </div>
        <Panel title={t("Certification scope")} description={t("Decision fields and their recorded provenance.")}>
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            <div><dt className="text-muted">{t("Assertion")}</dt><dd className="mt-1">{shown(detail.data.assertion)}</dd></div>
            <div><dt className="text-muted">{t("Verification window")}</dt><dd className="mt-1">{shown(detail.data.verification_window?.start)} → {shown(detail.data.verification_window?.end)}</dd></div>
            <div><dt className="text-muted">{t("Method")}</dt><dd className="mt-1">{shown(detail.data.family.method)}</dd></div>
            <div><dt className="text-muted">{t("Alpha / family size")}</dt><dd className="mt-1">{shown(detail.data.family.alpha)} / {shown(detail.data.family.family_size)}</dd></div>
            <div><dt className="text-muted">{t("Freeze fingerprint")}</dt><dd className="mt-1 break-all font-mono text-xs">{shown(detail.data.fingerprints.freeze)}</dd></div>
            <div><dt className="text-muted">{t("Source fingerprint")}</dt><dd className="mt-1 break-all font-mono text-xs">{shown(detail.data.source_sha256)}</dd></div>
          </dl>
        </Panel>
        <Panel title={t("Certified candidates")} className="mt-5" description={t("Status, adjusted p values and recorded periods are decision fields. All other columns are descriptive.")}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">{t("Certified candidates from this frozen round")}</caption>
              <thead className="border-b border-line"><tr><th className="py-2">{t("Factor")}</th><th>{t("Expression")}</th><th>{t("Status")}</th><th>{t("Adjusted p")}</th><th>{t("Mean rank IC")}</th><th>{t("Mean improvement")}</th><th>{t("Periods")}</th><th>{t("Effective")}</th></tr></thead>
              <tbody>
                {detail.data.candidates.length === 0 && <tr><td colSpan={8} className="py-3 text-muted">{t("No candidates recorded.")}</td></tr>}
                {detail.data.candidates.map(candidate => <tr key={shown(candidate.factor_id)} className="border-b border-line/50">
                  <th className="py-2 font-normal">{shown(candidate.factor_id)}</th>
                  <td><code className="break-all">{shown(candidate.expression)}</code></td>
                  <td>{shown(candidate.status)}</td>
                  <td>{shown(candidate.adjusted_p_value)}</td>
                  <td>{shown(candidate.mean_rank_ic)}</td>
                  <td>{shown(candidate.mean_improvement)}</td>
                  <td>{shown(candidate.periods)}</td>
                  <td>{candidate.effective ? "Yes" : "No"}</td>
                </tr>)}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title={t("Descriptive metrics")} className="mt-5" description={t("Report only. These values are not promotion gates and no new claim is inferred here.")}>
          {detail.data.descriptive_metrics === null
            ? <p className="text-sm text-muted">{t("No descriptive metrics recorded.")}</p>
            : <dl className="grid gap-4 text-sm sm:grid-cols-2">
              {Object.entries(detail.data.descriptive_metrics).map(([key, value]) => <div key={key}><dt className="text-muted">{key}</dt><dd className="mt-1 break-all text-xs">{shown(value)}</dd></div>)}
            </dl>}
        </Panel>
        <Panel title={t("Disclosure and boundaries")} className="mt-5">
          <div className="space-y-4 text-sm">
            <div><p className="text-muted">{t("Contamination disclosure")}</p><p className="mt-1">{shown(detail.data.disclosure.contamination)}</p></div>
            <div><p className="text-muted">{t("Data caveats")}</p><ul className="mt-1 list-disc pl-5">{detail.data.disclosure.data_caveats.length === 0 ? <li className="text-muted">{t("N/A")}</li> : detail.data.disclosure.data_caveats.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></div>
            <div><p className="text-muted">{t("Not claimed")}</p><ul className="mt-1 list-disc pl-5">{detail.data.disclosure.not_claimed.length === 0 ? <li className="text-muted">{t("N/A")}</li> : detail.data.disclosure.not_claimed.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></div>
            <div><p className="text-muted">{t("Limitations")}</p><p className="mt-1">{shown(detail.data.disclosure.limitations)}</p></div>
          </div>
        </Panel>
      </>}
    </>}

    <div className="mt-8">
      <PageHeader eyebrow={t("Research / Execution")} title={t("Execution demo")} description={t("Engineering closed-loop evidence. No new effectiveness claim is made.")} />
      {executions.isPending && <p role="status">{t("Loading execution demos…")}</p>}
      {executions.isError && <p role="alert">{executions.error.message}</p>}
      {executions.data?.length === 0 && <Panel title={t("No execution demos available")}><p className="text-sm text-muted">{t("No engineering execution demo was found.")}</p></Panel>}
      {Boolean(executions.data?.length) && <>
        <div className="mb-5 flex flex-wrap items-end gap-4">
          <label className="text-sm">"Execution demo"
            <select aria-label={t("Execution demo")} className="mt-1 block rounded border border-line bg-surface p-2" value={demoId} onChange={event => { setDemoSelection(event.target.value); }}>
              {executions.data!.map(row => <option key={row.demo_id} value={row.demo_id}>{row.demo_id}</option>)}
            </select>
          </label>
        </div>
        {demo.isPending && <p role="status">{t("Loading execution detail…")}</p>}
        {demo.isError && <p role="alert">{demo.error.message}</p>}
        {demo.data && <>
          <div className="metric-strip mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label={t("New claim")} value={demo.data.no_new_effectiveness_claim ? "None" : "Check source"} note={shown(demo.data.purpose)} />
            <Metric label={t("Timing candidates")} value={shown(demo.data.timing_demo.n_candidates)} note={t("Zero means no frozen timing rule")} />
            <Metric label={t("Replay identical")} value={demo.data.replay.identical === null ? "N/A" : demo.data.replay.identical ? "Yes" : "No"} />
            <Metric label={t("Backtest window")} value={shown(demo.data.backtest.window?.join(" → "))} />
          </div>
          {demo.data.frozen_strategy && <>
            <Panel title={t("Quantitative strategy")} description="Frozen selection + timing rules and Qlib-aligned execution metrics, read without recomputation. Report only; no effectiveness claim.">
              <p className="mb-3 text-[11px] uppercase tracking-wide text-muted">{t("Selection rule · Qlib TopkDropout style")}</p>
              <div className="metric-strip mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Metric label={t("Weight scheme")} value={shown(demo.data.frozen_strategy.selection.weight_config?.scheme)} note={demo.data.frozen_strategy.selection.verified ? "Verified against recorded fingerprint" : "N/A · not reconstructible"} />
                <Metric label={t("Top K")} value={shown(demo.data.frozen_strategy.selection.top_k)} />
                <Metric label={t("Drop / rebalance")} value={shown(demo.data.frozen_strategy.selection.weight_config?.drop)} note={t("Names changed per rebalance")} />
                <Metric label={t("Consumer factor")} value={shown(demo.data.frozen_strategy.selection.factor_ids)} />
              </div>
              <p className="mt-4 mb-3 text-[11px] uppercase tracking-wide text-muted">{t("Timing rule")}</p>
              <div className="metric-strip mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Metric label={t("Entry threshold")} value={shown(demo.data.frozen_strategy.timing.entry_threshold)} />
                <Metric label={t("Exit threshold")} value={shown(demo.data.frozen_strategy.timing.exit_threshold)} />
                <Metric label={t("Selected names")} value={shown(demo.data.frozen_strategy.timing.selected_symbol_count)} note={t("Frozen timing universe")} />
                <Metric label={t("Rule source")} value={demo.data.frozen_strategy.timing.is_fallback ? "Fallback" : "Certified"} note={demo.data.frozen_strategy.timing.is_fallback ? "No certified timing rule; zero threshold" : "Certified timing rule"} />
              </div>
              <dl className="mt-4 grid gap-4 border-t border-line pt-4 text-sm sm:grid-cols-2">
                <div><dt className="text-muted">{t("Selection rule fingerprint")}</dt><dd className="mt-1 break-all font-mono text-xs">{shown(demo.data.frozen_strategy.selection.fingerprint)}</dd></div>
                <div><dt className="text-muted">{t("Timing certification marker")}</dt><dd className="mt-1 break-all font-mono text-xs">{shown(demo.data.frozen_strategy.timing.certification_fingerprint)}</dd></div>
                <div><dt className="text-muted">{t("Timing candidates certified")}</dt><dd className="mt-1">{shown(demo.data.frozen_strategy.disclosure.n_candidates)}</dd></div>
                <div><dt className="text-muted">{t("Unreconstructible detail")}</dt><dd className="mt-1 text-xs">{demo.data.frozen_strategy.selection.verified ? "None" : "N/A · selection parameters"}</dd></div>
              </dl>
              <div className="mt-5 border-t border-line pt-4">
                <p className="mb-3 text-[11px] uppercase tracking-wide text-muted">{t("Execution metrics · Qlib risk_analysis aligned · report only")}</p>
                <div className="metric-strip grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <Metric label={t("Total return")} value={percent(demo.data.frozen_strategy.risk.total_return)} />
                  <Metric label={t("Max drawdown")} value={percent(demo.data.frozen_strategy.risk.max_drawdown)} />
                  <Metric label={t("Turnover")} value={shown(demo.data.frozen_strategy.risk.turnover)} />
                  <Metric label={t("Sharpe")} value={shown(demo.data.frozen_strategy.risk.sharpe_ratio)} />
                  <Metric label={t("Annualized vol")} value={shown(demo.data.frozen_strategy.risk.annualized_volatility)} />
                  <Metric label={t("Final equity")} value={shown(demo.data.frozen_strategy.risk.final_equity)} />
                  <Metric label={t("Bars")} value={shown(demo.data.frozen_strategy.risk.bar_count)} />
                  <Metric label={t("Fills / rejected")} value={`${shown(demo.data.frozen_strategy.risk.fill_count)} / ${shown(demo.data.frozen_strategy.risk.rejected_count)}`} />
                  <Metric label={t("Final positions")} value={shown(demo.data.frozen_strategy.risk.final_position_count)} />
                  <Metric label={t("Clock reconcile")} value={shown(demo.data.frozen_strategy.risk.reconciliation_max_abs)} />
                </div>
              </div>
            </Panel>
          </>}
          <Panel title={t("Provenance and rules")} className="mt-5" description={t("Recorded fingerprints and data caveats from the audit summary.")}>
            <dl className="grid gap-4 text-sm sm:grid-cols-2">
              <div><dt className="text-muted">{t("Consumed factor")}</dt><dd className="mt-1">{shown(demo.data.consumed_factor.factor_id)}</dd></div>
              <div><dt className="text-muted">{t("Evidence fingerprint")}</dt><dd className="mt-1 break-all font-mono text-xs">{shown(demo.data.consumed_factor.evidence_fingerprint)}</dd></div>
              <div><dt className="text-muted">{t("Selection rule")}</dt><dd className="mt-1 break-all font-mono text-xs">{shown(demo.data.selection_rule_fingerprint)}</dd></div>
              <div><dt className="text-muted">{t("Timing rule")}</dt><dd className="mt-1 break-all font-mono text-xs">{shown(demo.data.timing_rule_fingerprint)}</dd></div>
              <div><dt className="text-muted">{t("Universe")}</dt><dd className="mt-1">{shown(demo.data.data_provenance.universe)} · {shown(demo.data.data_provenance.symbols)} symbols</dd></div>
              <div><dt className="text-muted">{t("Survivorship bias")}</dt><dd className="mt-1">{shown(demo.data.data_provenance.survivorship_bias)}</dd></div>
            </dl>
          </Panel>
          <Panel title={t("Backtest summary")} className="mt-5" description={t("Execution demonstration only. Missing statistics are shown as N/A, never zero.")}>
            <div className="metric-strip grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Metric label={t("Total return")} value={percent(demo.data.backtest.metrics.total_return as number | null)} />
              <Metric label={t("Max drawdown")} value={percent(demo.data.backtest.metrics.max_drawdown as number | null)} />
              <Metric label={t("Turnover")} value={shown(demo.data.backtest.metrics.turnover)} />
              <Metric label={t("Fills / rejected")} value={`${shown(demo.data.backtest.metrics.fill_count)} / ${shown(demo.data.backtest.metrics.rejected_count)}`} />
            </div>
            <p className="mt-4 text-xs text-muted">Sharpe: {shown(demo.data.backtest.metrics.sharpe_ratio)} · Annualized volatility: {shown(demo.data.backtest.metrics.annualized_volatility)} · Clock reconciliation: {shown(demo.data.backtest.metrics.reconciliation_max_abs)}</p>
          </Panel>
        </>}
      </>}
    </div>

    <div className="mt-8">
      <PageHeader eyebrow={t("Research / Robustness")} title={t("Walk-forward robustness")} description={t("Rule-driven rolling out-of-sample folds. One frozen family, disjoint test windows, no pooled p-values and no new effectiveness claim.")} />
      {walkRounds.isPending && <p role="status">{t("Loading walk-forward diagnostics…")}</p>}
      {walkRounds.isError && <p role="alert">{walkRounds.error.message}</p>}
      {walkRounds.data?.length === 0 && <Panel title={t("No walk-forward diagnostics available")}><p className="text-sm text-muted">{t("No rule-driven rolling diagnostic was found in the configured directory.")}</p></Panel>}
      {Boolean(walkRounds.data?.length) && <>
        <div className="mb-5 flex flex-wrap items-end gap-4">
          <label className="text-sm">"Diagnostic"
            <select aria-label={t("Walk-forward diagnostic")} className="mt-1 block rounded border border-line bg-surface p-2" value={walkId} onChange={event => { setWalkSelection(event.target.value); }}>
              {walkRounds.data!.map(row => <option key={row.directory} value={row.directory}>{row.directory} · {shown(row.fold_count)} folds</option>)}
            </select>
          </label>
        </div>
        {walk.isPending && <p role="status">{t("Loading walk-forward detail…")}</p>}
        {walk.isError && <p role="alert">{walk.error.message}</p>}
        {walk.data && <>
          <div className="metric-strip mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label={t("Folds")} value={shown(walk.data.fold_count)} note={shown(walk.data.channel_label)} />
            <Metric label={t("Effective / refuted")} value={`${walk.data.counts.effective.length} / ${walk.data.counts.refuted.length}`} note={walk.data.flags.no_pooled_p_value ? "Per-fold tests; p-values not pooled" : "Check source"} />
            <Metric label={t("Insufficient evidence")} value={String(walk.data.counts.insufficient_evidence.length)} note={t("Low power or stability gates not met")} />
            <Metric label={t("New claim")} value={walk.data.flags.no_new_effectiveness_claim ? "None" : "Check source"} note={shown(walk.data.purpose)} />
          </div>
          <Panel title={t("Fold comparison matrix")} description="Multi-run comparison following Qlib rolling retraining and the upstream research-matrix convention. Each fold has its own family test; status and family p are decision fields, rank IC is descriptive.">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <caption className="sr-only">{t("Walk-forward folds of one frozen learned-factor family")}</caption>
                <thead className="border-b border-line"><tr><th className="py-2">{t("Fold")}</th><th>{t("Test window")}</th><th>{t("Freeze cutoff")}</th><th>{t("Periods")}</th><th>{t("Family p")}</th><th>{t("Rank IC")}</th><th>{t("Status")}</th><th>{t("Effective")}</th></tr></thead>
                <tbody>
                  {walk.data.folds.length === 0 && <tr><td colSpan={8} className="py-3 text-muted">{t("No folds recorded.")}</td></tr>}
                  {walk.data.folds.map(fold => <tr key={shown(fold.fold)} className="border-b border-line/50">
                    <th className="py-2 font-normal">{shown(fold.fold)}</th>
                    <td>{fold.test_window.filter(Boolean).join(" → ") || "N/A"}</td>
                    <td>{shown(fold.cutoff)}</td>
                    <td>{shown(fold.periods)}</td>
                    <td className="tabular-nums">{fixed(fold.family_p_value)}</td>
                    <td className="tabular-nums">{fixed(fold.rank_ic)}</td>
                    <td>{shown(fold.status)}</td>
                    <td>{fold.effective ? "Yes" : "No"}</td>
                  </tr>)}
                </tbody>
              </table>
            </div>
            <p className="mt-4 text-xs text-muted">Rank IC by fold: {walk.data.rank_ic_series.length === 0 ? "N/A" : walk.data.rank_ic_series.map(item => fixed(item.rank_ic)).join(" · ")}</p>
          </Panel>
          <Panel title={t("Scope and caveats")} className="mt-5" description={t("Read-only disclosures from the frozen diagnostic and its audit addendum.")}>
            <div className="space-y-4 text-sm">
              <div><p className="text-muted">{t("Statistical power")}</p><p className="mt-1">{shown(walk.data.disclosure.power_warning)}</p></div>
              <div><p className="text-muted">Descriptive observation (report only)</p><p className="mt-1">{shown(walk.data.disclosure.descriptive_observation)}</p></div>
              <div><p className="text-muted">{t("Contamination addendum")}</p><p className="mt-1">{shown(walk.data.disclosure.contamination_addendum)}</p></div>
              <div><p className="text-muted">{t("Upstream authority")}</p><p className="mt-1">{shown(walk.data.disclosure.upstream_authority)}</p></div>
              <div><p className="text-muted">{t("Not claimed")}</p><ul className="mt-1 list-disc pl-5">{walk.data.disclosure.not_claimed.length === 0 ? <li className="text-muted">{t("N/A")}</li> : walk.data.disclosure.not_claimed.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></div>
              <div><p className="text-muted">{t("Provenance")}</p><p className="mt-1 break-all font-mono text-xs">Freeze {shown(walk.data.freeze_fingerprint)} · Source certification {shown(walk.data.source_certification_sha256)}</p></div>
            </div>
          </Panel>
        </>}
      </>}
    </div>
  </>;
}
