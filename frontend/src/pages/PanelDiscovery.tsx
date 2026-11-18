import { useState } from "react";
import { Panel } from "../components/shared/Panel";
import { useTranslation } from "react-i18next";

type Decision = {
  date: string; maturity: string; training_last_maturity: string;
  candidate: string | null; random_candidate: string | null;
  baseline_rank_ic: number; discovery_gain: number; random_gain: number;
  ranked: number; scored: number;
};
type Interval = { mean: number | null; low: number | null; high: number | null };
type ForwardDecision = {
  month: string; decision: string; committed_at: string; data_through: string;
  source_sha256: string; candidate: string | null; ranked: number;
  settlement: null | { maturity: string; scored: number; committed_before_maturity: boolean;
    baseline_rank_ic: number | null; selected_rank_ic: number | null };
};
export type PanelEvidence = {
  universe: string;
  summary: {
    archive_sha256: string; candidates: string[]; lookback: number; random_seed: number;
    periods: Record<string, { months: number; active: number; discovery_minus_fixed: Interval;
      random_minus_fixed: Interval; discovery_minus_random: Interval }>;
  };
  decisions: Decision[];
  forward_decisions?: ForwardDecision[];
};

const format = (value: number | null) => value == null ? "—" : value.toFixed(4);
const interval = ({ low, high }: Interval) => low == null || high == null
  ? "Unavailable" : `[${format(low)}, ${format(high)}]`;

export function PanelDiscovery({ data }: { data: PanelEvidence }) {
  const { t } = useTranslation();
  const [year, setYear] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const years = [...new Set(data.decisions.map(row => row.date.slice(0, 4)))];
  const selectedYear = year || years.at(-1) || "";
  const rows = data.decisions.filter(row => row.date.startsWith(selectedYear) && (!activeOnly || row.candidate));
  return <div className="space-y-5">
    {!!data.forward_decisions?.length && <Panel title={t("Recorded forward decisions")} description={t("Compare the decision date with the actual submission time and input cutoff.")}>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm tabular-nums">
        <thead><tr className="border-b border-line">{[t("Decision"), t("Submitted (UTC)"), t("Data through"), t("Formula"), t("Coverage"), t("Label maturity"), t("Equal-weight IC"), t("Selected IC")].map(label => <th scope="col" key={label} className="p-2">{label}</th>)}</tr></thead>
        <tbody>{data.forward_decisions.map(row => <tr key={row.month} className="border-b border-line/50">
          <th scope="row" className="whitespace-nowrap p-2" title={`Dataset SHA-256 ${row.source_sha256}`}>{row.decision}</th>
          <td className="whitespace-nowrap p-2"><time dateTime={row.committed_at}>{row.committed_at.slice(0, 16).replace("T", " ")}</time></td>
          <td className="whitespace-nowrap p-2">{row.data_through}</td>
          <td className="p-2">{row.candidate ?? "Equal weight"}</td>
          <td className="whitespace-nowrap p-2">{row.settlement ? `${row.settlement.scored} / ${row.ranked}` : `${row.ranked} ranked`}</td>
          <td className="whitespace-nowrap p-2">{row.settlement?.maturity ?? "Pending"}{row.settlement?.committed_before_maturity === false && <span className="block text-xs text-muted">{t("Submitted at or after maturity")}</span>}</td>
          <td className="p-2">{format(row.settlement?.baseline_rank_ic ?? null)}</td>
          <td className="p-2">{format(row.settlement?.selected_rank_ic ?? null)}</td>
        </tr>)}</tbody>
      </table></div>
    </Panel>}
    <Panel title={`${data.universe} · Interaction search`} description={t("Paired monthly Rank IC on stocks with observed forward labels.")}>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm tabular-nums">
        <thead><tr className="border-b border-line">{[t("Period"), t("Active months"), t("Selected − equal weight"), t("Random − equal weight"), t("Selected − random"), t("95% interval vs equal weight")].map(label => <th scope="col" key={label} className="p-2">{label}</th>)}</tr></thead>
        <tbody>{Object.entries(data.summary.periods).map(([period, row]) => <tr key={period} className="border-b border-line/50">
          <th scope="row" className="p-2">{period}</th><td className="p-2">{row.active} / {row.months}</td>
          <td className="p-2">{format(row.discovery_minus_fixed.mean)}</td><td className="p-2">{format(row.random_minus_fixed.mean)}</td>
          <td className="p-2">{format(row.discovery_minus_random.mean)}</td><td className="p-2">{interval(row.discovery_minus_fixed)}</td>
        </tr>)}</tbody>
      </table></div>
    </Panel>
    <Panel title={t("Monthly decisions")} description={t("Months without a selected formula use the equal-weight baseline.")}>
      <div className="mb-3 flex flex-wrap items-center gap-4 text-sm">
        <label>{t("Decision year")} <select className="rounded border border-line bg-surface p-2" value={selectedYear} onChange={e => setYear(e.target.value)}>{years.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={activeOnly} onChange={e => setActiveOnly(e.target.checked)} /> {t("Selected formulas only")}</label>
      </div>
      {rows.length === 0 ? <p className="text-sm text-muted">{t("No matching decisions.")}</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm tabular-nums">
        <thead><tr className="border-b border-line">{[t("Decision"), t("Training cutoff"), t("Label maturity"), t("Selected formula"), t("Random formula"), t("Equal-weight IC"), t("Selected Δ"), t("Random Δ"), t("Scored / ranked")].map(label => <th scope="col" key={label} className="p-2">{label}</th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.date} className="border-b border-line/50">
          <th scope="row" className="whitespace-nowrap p-2 font-medium">{row.date}</th>
          <td className="whitespace-nowrap p-2">{row.training_last_maturity}</td><td className="whitespace-nowrap p-2">{row.maturity}</td>
          <td className="p-2"><code className="text-xs">{row.candidate ?? "Abstained"}</code></td><td className="p-2"><code className="text-xs">{row.random_candidate ?? "—"}</code></td>
          <td className="p-2">{format(row.baseline_rank_ic)}</td><td className="p-2">{format(row.discovery_gain)}</td><td className="p-2">{format(row.random_gain)}</td>
          <td className="whitespace-nowrap p-2">{row.scored} / {row.ranked}</td>
        </tr>)}</tbody>
      </table></div>}
    </Panel>
    <Panel title={t("Run provenance")} description={`${data.summary.lookback} matured months per selection · random seed ${data.summary.random_seed}`}>
      <p className="break-all text-xs text-muted">{t("Dataset SHA-256")} <code>{data.summary.archive_sha256}</code></p>
      <ul className="mt-3 space-y-1 text-sm">{data.summary.candidates.map(formula => <li key={formula}><code>{formula}</code></li>)}</ul>
    </Panel>
  </div>;
}
