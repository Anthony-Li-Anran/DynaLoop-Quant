import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../features/api";
import {
  generateSubjective,
  type LlmConfig,
  type SubjectiveResult,
} from "../features/subjectiveLlm";
import type { ExperienceStar, LivingStrategy } from "../features/api";
import { PageHeader } from "../components/shared/PageHeader";
import { Panel } from "../components/shared/Panel";
import { useTranslation } from "react-i18next";

function shown(value: unknown): string {
  if (value === null || value === undefined) return "N/A";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "N/A";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function availability(record: unknown): string {
  const obj = record as { available?: boolean } | null;
  if (!obj) return "N/A";
  return obj.available ? "Available" : "Unavailable";
}

export function SubjectivePage() {
  const { t } = useTranslation();
  const [symbols, setSymbols] = useState("600519");
  const [decisionTime, setDecisionTime] = useState("");
  const [liveNews, setLiveNews] = useState(false);
  const [context, setContext] = useState<Record<string, unknown> | null>(null);
  const [output, setOutput] = useState<SubjectiveResult | null>(null);
  const [streamText, setStreamText] = useState("");
  const [strategyQuery, setStrategyQuery] = useState("");

  const library = useQuery({ queryKey: ["strategy-library"], queryFn: api.strategyLibrary });

  const cfg = useQuery({ queryKey: ["subjective-llm-config"], queryFn: api.subjectiveLlmConfig });
  const inputs = useMutation({
    mutationFn: () =>
      api.subjectiveInputs({
        decision_time: decisionTime || undefined,
        symbols: symbols.split(/[\s,]+/).filter(Boolean),
        live_news: liveNews,
        strategy_query: strategyQuery || undefined,
      }),
    onSuccess: (data) => {
      setContext(data);
      setOutput(null);
      setStreamText("");
    },
  });
  const generate = useMutation({
    mutationFn: async () => {
      if (!context || !cfg.data) throw new Error("context or config not ready");
      setStreamText("");
      const config: LlmConfig = cfg.data;
      return generateSubjective({
        config,
        context,
        onToken: (piece) => setStreamText((prev) => prev + piece),
      });
    },
    onSuccess: (result) => setOutput(result),
  });

  const feed = (context?.inputs ?? {}) as Record<string, unknown>;
  const news = (feed.news ?? {}) as { provider?: { available?: boolean }; count?: number };
  const strategies = (feed.strategy_library ?? {}) as { candidates?: unknown[] };
  const consulted = (strategies.candidates ?? []) as LivingStrategy[];
  const experience = library.data?.experience ?? {};

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={t("Decision / Subjective")}
        title={t("Subjective Analysis")}
        description={t("Real LLM-backed subjective reading over a shared point-in-time context. Output is for human review only.")}
      />

      <Panel title={t("Input context")} description={t("Four shared inputs: A-share data, news, sentiment and strategy library.")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">
            <span className="block text-muted">Symbols (comma separated)</span>
            <input className="mt-1 w-full rounded border border-line bg-elevated p-2"
              value={symbols} onChange={(e) => setSymbols(e.target.value)} />
          </label>
          <label className="text-sm">
            <span className="block text-muted">Decision time (optional)</span>
            <input className="mt-1 w-full rounded border border-line bg-elevated p-2"
              placeholder="2026-11-18" value={decisionTime}
              onChange={(e) => setDecisionTime(e.target.value)} />
          </label>
          <label className="text-sm">
            <span className="block text-muted">Strategy query (market context)</span>
            <input className="mt-1 w-full rounded border border-line bg-elevated p-2"
              placeholder={t("trend momentum")} value={strategyQuery}
              onChange={(e) => setStrategyQuery(e.target.value)} />
          </label>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={liveNews}
            onChange={(e) => setLiveNews(e.target.checked)} />
          <span>Fetch live news (best-effort)</span>
        </label>
        <div className="mt-4 flex gap-3">
          <button className="rounded bg-accent px-4 py-2 text-sm"
            disabled={inputs.isPending} onClick={() => inputs.mutate()}>
            {inputs.isPending ? "Loading..." : "Build context"}
          </button>
          <button className="rounded border border-line px-4 py-2 text-sm"
            disabled={!context || !cfg.data?.enabled || generate.isPending}
            onClick={() => generate.mutate()}>
            {generate.isPending ? "Generating..." : "Generate subjective reading"}
          </button>
        </div>
        {inputs.isError && <p role="alert" className="mt-3 text-sm text-danger">{t("Failed to build context.")}</p>}
        {cfg.isError && <p role="alert" className="mt-3 text-sm text-danger">{t("LLM config unavailable.")}</p>}
      </Panel>

      {context && <Panel title={t("Context summary")} description="Point-in-time aligned inputs; missing sources stay unavailable.">
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="rounded border border-line bg-elevated p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted">{t("A-share data")}</p>
            <p className="mt-1 text-lg">{availability(feed.a_share_data)}</p>
          </div>
          <div className="rounded border border-line bg-elevated p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted">{t("News")}</p>
            <p className="mt-1 text-lg">{availability(news.provider)}</p>
            <p className="mt-1 text-[11px] text-muted">{shown(news.count)} admitted records</p>
          </div>
          <div className="rounded border border-line bg-elevated p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted">{t("Sentiment")}</p>
            <p className="mt-1 text-lg">{availability(feed.sentiment)}</p>
          </div>
          <div className="rounded border border-line bg-elevated p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted">{t("Strategy library")}</p>
            <p className="mt-1 text-lg">{shown(strategies.candidates?.length)}</p>
          </div>
        </div>
      </Panel>}

      <Panel
        title={t("Living strategy library")}
        description={t("Harvested candidate practices with report-only experience stars. Not a factor, verdict or return claim.")}
      >
        <p className="text-[11px] text-muted">
          {library.isLoading
            ? "Loading library..."
            : `${shown(library.data?.count)} strategies stored · ${Object.keys(experience).length} with experience`}
        </p>
        {consulted.length > 0 && (
          <div className="mt-3 space-y-2">
            <p className="text-[11px] uppercase tracking-wide text-muted">{t("Consulted for this context")}</p>
            {consulted.map((strategy) => {
              const star: ExperienceStar | undefined = experience[strategy.entry_id];
              return (
                <div key={strategy.entry_id ?? strategy.name} className="rounded border border-line bg-elevated p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm">{strategy.name}</span>
                    <span className="text-[11px] text-muted">
                      {star?.has_evidence ? `${shown(star.stars)} / 5 stars` : "no evidence"}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-muted">
                    {strategy.method ?? "method N/A"} · {strategy.author ?? "unknown author"}
                  </p>
                  <p className="mt-1 text-[11px] text-muted">
                    Regimes: {(strategy.regimes ?? []).length ? strategy.regimes.join(", ") : "N/A"}
                    {" · available "}{shown(strategy.available_at)}
                    {" · source "}{shown(strategy.source_name)}
                  </p>
                </div>
              );
            })}
          </div>
        )}
        {consulted.length === 0 && (
          <p className="mt-3 text-[11px] text-muted">
            {t("Build a context with a strategy query to retrieve relevant strategies for the subjective reading.")}
          </p>
        )}
      </Panel>

      {(generate.isPending || output || streamText) && <Panel
        title={t("Subjective reading")}
        description={t("Model output. Not a factor, not a verdict, not investment advice. Human review required.")}>
        <pre className="whitespace-pre-wrap rounded border border-line bg-elevated p-4 text-sm">
          {streamText || output?.text || ""}
        </pre>
        {output && <p className="mt-3 text-[11px] text-muted">
          Model: {shown(output.model)} · finished: {String(output.finished)}
        </p>}
        {generate.isError && <p role="alert" className="mt-3 text-sm text-danger">{t("Model call failed.")}</p>}
      </Panel>}
    </div>
  );
}
