import { useQuery } from "@tanstack/react-query";
import { Play, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "../../components/ui/Button";
import { Drawer } from "../../components/ui/Drawer";
import { SelectField } from "../../components/ui/SelectField";
import { Panel } from "../../components/shared/Panel";
import { QueryState } from "../../components/shared/States";
import { useTranslation } from "react-i18next";
import {
  api,
  type BacktestRunResponse,
  type BacktestSource,
  type QuickRunInput,
  type StrategyCatalogEntry,
} from "../api";

type RunSetupProps = {
  onRun: (response: BacktestRunResponse) => void;
};

const CUSTOM = "__custom__";

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="text-[13px] font-medium text-ink">{label}</span>
      <span className="mt-1 block">{children}</span>
      {hint && <span className="mt-1 block text-xs leading-5 text-muted">{hint}</span>}
    </label>
  );
}

const inputClass =
  "min-h-10 w-full rounded-md border border-line bg-canvas px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

export function RunSetup({ onRun }: RunSetupProps) {
  const { t } = useTranslation();
  const sources = useQuery({ queryKey: ["backtests", "sources"], queryFn: api.backtestSources });
  const catalog = useQuery({ queryKey: ["backtests", "strategies"], queryFn: api.strategyCatalog });

  const [sourceKey, setSourceKey] = useState("tencent_ashare");
  const [symbolChoice, setSymbolChoice] = useState("sh600000");
  const [customSymbol, setCustomSymbol] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [frequency, setFrequency] = useState("1d");
  const [adjust, setAdjust] = useState("qfq");
  const [initialCash, setInitialCash] = useState("100000");
  const [strategyClass, setStrategyClass] = useState("BuyAndHold");
  const [parameterValues, setParameterValues] = useState<Record<string, string>>({});
  const [customClass, setCustomClass] = useState("");
  const [customJson, setCustomJson] = useState("{}");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [executionMode, setExecutionMode] = useState("next_bar");
  const [executionPrice, setExecutionPrice] = useState("open");
  const [markPrice, setMarkPrice] = useState("close");
  const [commissionRate, setCommissionRate] = useState("0.0003");
  const [minCommission, setMinCommission] = useState("5");
  const [periodsPerYear, setPeriodsPerYear] = useState("252");
  const [runStart, setRunStart] = useState("");
  const [runEnd, setRunEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sourceList = sources.data ?? [];
  const strategyList = catalog.data ?? [];
  const source: BacktestSource | undefined =
    sourceList.find((item) => item.key === sourceKey) ?? sourceList[0];
  const strategyEntry: StrategyCatalogEntry | undefined = strategyList.find(
    (item) => item.class === strategyClass,
  );
  const isCustom = strategyClass === CUSTOM;

  const lastSourceKey = useRef<string | null>(null);

  // Each source declares its own sensible window (intraday sources point at
  // recent sessions). Reset only when the source changes, never while the user
  // is editing the two date fields.
  useEffect(() => {
    if (!source) return;
    if (lastSourceKey.current === sourceKey && start && end) return;
    lastSourceKey.current = sourceKey;
    setStart(source.default_start || "2024-01-02");
    setEnd(source.default_end || "2024-06-28");
  }, [source, sourceKey, start, end]);

  useEffect(() => {
    if (!source || source.symbols.length === 0) return;
    if (!source.symbols.some((item) => item.symbol === symbolChoice) && symbolChoice !== CUSTOM) {
      setSymbolChoice(source.symbols[0].symbol);
    }
  }, [source, symbolChoice]);

  // A source declares the periods it can express. Keep the selection inside
  // that declaration when switching sources; the input still accepts any value
  // the source knows, so a newly registered source needs no front-end change.
  useEffect(() => {
    if (!source || !source.controllable.includes("frequency")) return;
    const options = source.frequencies;
    if (!options.length || options.some((option) => option.value === frequency)) return;
    const daily = options.find((option) => option.value === "1d");
    setFrequency(daily?.value ?? options[0].value);
  }, [source, frequency]);

  useEffect(() => {
    if (isCustom) return;
    const defaults: Record<string, string> = {};
    for (const parameter of strategyEntry?.parameters ?? []) {
      defaults[parameter.key] = String(parameter.default);
    }
    setParameterValues(defaults);
  }, [strategyClass, strategyEntry, isCustom]);

  const symbolOptions = useMemo(() => {
    const listed = (source?.symbols ?? []).map((item) => ({
      value: item.symbol,
      label: `${item.symbol} · ${item.name} (${item.kind})`,
    }));
    if (!listed.length) {
      // A source with no controllable instrument parameter still needs a label
      // for the bars it returns; never invent a catalogue it did not declare.
      const fallback = symbolChoice === CUSTOM ? "sh600000" : symbolChoice;
      listed.push({ value: fallback, label: `${fallback} · Instrument defined by source` });
    }
    return [...listed, { value: CUSTOM, label: t("Other code…") }];
  }, [source, symbolChoice]);

  const strategyOptions = useMemo(
    () =>
      strategyList.map((item) => ({
        value: item.class,
        label: item.label,
      })),
    [strategyList],
  );

  function buildPayload(): QuickRunInput {
    const resolvedSymbol = symbolChoice === CUSTOM ? customSymbol.trim() : symbolChoice;
    if (!resolvedSymbol) throw new Error("Enter an instrument code.");
    if (!isFinite(Number(initialCash)) || Number(initialCash) <= 0) {
      throw new Error("Initial capital must be a positive number.");
    }

    let strategyKwargs: Record<string, unknown> = {};
    let resolvedClass = strategyClass;
    if (isCustom) {
      if (!customClass.trim()) throw new Error("Enter a strategy class or module.Class path.");
      let parsed: unknown;
      try {
        parsed = JSON.parse(customJson || "{}");
      } catch {
        throw new Error("Strategy parameters must be valid JSON.");
      }
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("Strategy parameters must be a JSON object.");
      }
      strategyKwargs = parsed as Record<string, unknown>;
      resolvedClass = customClass.trim();
    } else {
      for (const parameter of strategyEntry?.parameters ?? []) {
        const raw = parameterValues[parameter.key];
        const value = Number(raw);
        if (!Number.isFinite(value)) throw new Error(`${parameter.label} must be a number.`);
        strategyKwargs[parameter.key] = parameter.type === "integer" ? Math.trunc(value) : value;
      }
    }

    const execution: Record<string, unknown> = {
      execution_mode: executionMode,
      execution_price: executionPrice,
      mark_price: markPrice,
      commission_rate: Number(commissionRate),
      min_commission: Number(minCommission),
      periods_per_year: Number(periodsPerYear),
    };

    return {
      source_key: source?.key ?? sourceKey,
      symbol: resolvedSymbol,
      start: start || null,
      end: end || null,
      ...(runStart ? { run_start: runStart } : {}),
      ...(runEnd ? { run_end: runEnd } : {}),
      frequency,
      adjust,
      initial_cash: Number(initialCash),
      strategy_class: resolvedClass,
      strategy_kwargs: strategyKwargs,
      execution,
      label: `${resolvedSymbol} · ${isCustom ? "Custom" : strategyEntry?.label ?? resolvedClass}`,
    };
  }

  async function submit() {
    setError(null);
    let payload: QuickRunInput;
    try {
      payload = buildPayload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Invalid setup.");
      return;
    }
    setBusy(true);
    try {
      const response = await api.quickRun(payload);
      onRun(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Backtest failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Panel
        title={t("New backtest")}
        description={t("Choose a data source, an instrument, a window and a classic strategy. No JSON needed unless you pick Custom strategy.")}
      >
        <QueryState query={sources} emptyTitle={t("No data sources available")}>
          {() => (
            <div className="space-y-5">
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-4">
                  <SelectField
                    label={t("1 · Data source")}
                    value={source?.key ?? sourceKey}
                    onChange={setSourceKey}
                    options={sourceList.map((item) => ({
                      value: item.key,
                      label: `${item.name}${item.compatible ? "" : " (not ready)"}`,
                    }))}
                    description={source?.capability_error || source?.description || undefined}
                  />
                  {(source?.columns ?? []).length > 0 && (
                    <div className="rounded-md border border-line bg-canvas/40 px-3 py-2">
                      <div className="text-[13px] font-medium text-ink">{t("Fields from this source")}</div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {(source?.columns ?? []).map((column) => (
                          <span
                            key={column}
                            className="rounded border border-line px-1.5 py-0.5 font-mono text-xs text-ink"
                          >
                            {column}
                            {source?.inferred_columns.includes(column) ? " (inferred)" : ""}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <SelectField
                    label={t("2 · Instrument")}
                    value={symbolChoice}
                    onChange={setSymbolChoice}
                    options={symbolOptions}
                    description={
                      source?.symbols.length
                        ? "Instruments declared by the selected source."
                        : undefined
                    }
                  />
                  {symbolChoice === CUSTOM && (
                    <Field label={t("Instrument code")} hint={t("Any code the source accepts, e.g. sh600000 or sz159915.")}>
                      <input
                        className={inputClass}
                        value={customSymbol}
                        onChange={(event) => setCustomSymbol(event.target.value)}
                        placeholder="sh600000"
                        aria-label={t("Instrument code")}
                      />
                    </Field>
                  )}
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label={t("Frequency")}>
                      <input
                        className={inputClass}
                        list="frequency-options"
                        value={
                          source?.controllable.includes("frequency")
                            ? frequency
                            : "Fixed by source"
                        }
                        onChange={(event) => setFrequency(event.target.value)}
                        disabled={!source?.controllable.includes("frequency")}
                        aria-label={t("Frequency")}
                        placeholder={t("1d")}
                      />
                      <datalist id="frequency-options">
                        {(source?.controllable.includes("frequency")
                          ? source.frequencies
                          : []
                        ).map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </datalist>
                    </Field>
                    <SelectField
                      label={t("Adjustment")}
                      value={adjust}
                      onChange={setAdjust}
                      disabled={!source?.controllable.includes("adjust")}
                      options={
                        source?.controllable.includes("adjust")
                          ? source.adjustments.length
                            ? source.adjustments
                            : [{ value: "qfq", label: "qfq" }]
                          : [{ value: "qfq", label: t("Fixed by source") }]
                      }
                    />
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label={t("3 · Window start")}>
                      <input
                        type="date"
                        aria-label={t("Window start")}
                        className={inputClass}
                        value={start}
                        onChange={(event) => setStart(event.target.value)}
                      />
                    </Field>
                    <Field label={t("Window end")}>
                      <input
                        type="date"
                        aria-label={t("Window end")}
                        className={inputClass}
                        value={end}
                        onChange={(event) => setEnd(event.target.value)}
                      />
                    </Field>
                  </div>
                  <Field label="4 · Initial capital (¥)">
                    <input
                      type="number"
                      min={1}
                      step={1000}
                      aria-label={t("Initial capital")}
                      className={inputClass}
                      value={initialCash}
                      onChange={(event) => setInitialCash(event.target.value)}
                    />
                  </Field>
                  <SelectField
                    label={t("5 · Strategy")}
                    value={strategyClass}
                    onChange={setStrategyClass}
                    options={strategyOptions.length ? strategyOptions : [{ value: "BuyAndHold", label: t("Buy & hold") }]}
                    description={isCustom ? "Provide a class and its kwargs as JSON." : strategyEntry?.summary}
                  />

                  {isCustom ? (
                    <div className="space-y-3 rounded-md border border-line bg-elevated/20 p-3">
                      <Field label={t("Strategy class")} hint={t("Registry name or importable module.Class path.")}>
                        <input
                          aria-label={t("Custom strategy class")}
                          className={inputClass}
                          value={customClass}
                          onChange={(event) => setCustomClass(event.target.value)}
                          placeholder={t("BuyAndHold")}
                        />
                      </Field>
                      <Field label="Strategy parameters (JSON)">
                        <textarea
                          aria-label={t("Custom strategy parameters JSON")}
                          className="min-h-24 w-full rounded-md border border-line bg-canvas p-3 font-mono text-xs text-ink"
                          value={customJson}
                          onChange={(event) => setCustomJson(event.target.value)}
                          spellCheck={false}
                        />
                      </Field>
                    </div>
                  ) : (
                    strategyEntry && strategyEntry.parameters.length > 0 && (
                      <div className="grid gap-3 rounded-md border border-line bg-elevated/20 p-3 sm:grid-cols-2">
                        {strategyEntry.parameters.map((parameter) => (
                          <Field key={parameter.key} label={parameter.label}>
                            <input
                              type="number"
                              aria-label={parameter.label}
                              className={inputClass}
                              value={parameterValues[parameter.key] ?? String(parameter.default)}
                              min={parameter.min}
                              max={parameter.max}
                              step={parameter.step ?? 1}
                              onChange={(event) =>
                                setParameterValues((values) => ({
                                  ...values,
                                  [parameter.key]: event.target.value,
                                }))
                              }
                            />
                          </Field>
                        ))}
                      </div>
                    )
                  )}
                </div>
              </div>

              {error && (
                <p role="alert" className="rounded-md border border-red-400/40 bg-red-400/10 px-3 py-2 text-sm text-red-300">
                  {error}
                </p>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line/70 pt-4">
                <Button variant="secondary" size="sm" onClick={() => setAdvancedOpen(true)}>
                  <SlidersHorizontal className="h-4 w-4" />
                  Execution &amp; replay window
                </Button>
                <Button variant="primary" onClick={submit} disabled={busy}>
                  <Play className="h-4 w-4" />
                  {busy ? "Running…" : "Run backtest"}
                </Button>
              </div>
            </div>
          )}
        </QueryState>
      </Panel>

      <Drawer
        open={advancedOpen}
        title={t("Execution & replay window")}
        description="These are explicit engine knobs (ml4t BacktestConfig). Defaults are safe; the run window can be narrower than the fetched window."
        onClose={() => setAdvancedOpen(false)}
      >
        <div className="space-y-4">
          <SelectField
            label={t("Fill timing")}
            value={executionMode}
            onChange={setExecutionMode}
            options={[
              { value: "next_bar", label: t("Next bar (no look-ahead)") },
              { value: "same_bar", label: t("Same bar (emits warning)") },
            ]}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label={t("Fill price")}
              value={executionPrice}
              onChange={setExecutionPrice}
              options={[
                { value: "open", label: "Open" },
                { value: "close", label: t("Close") },
                { value: "high", label: "High" },
                { value: "low", label: "Low" },
              ]}
            />
            <SelectField
              label={t("Mark price")}
              value={markPrice}
              onChange={setMarkPrice}
              options={[
                { value: "close", label: t("Close") },
                { value: "open", label: "Open" },
                { value: "price", label: t("Canonical price") },
              ]}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("Commission rate")}>
              <input
                type="number"
                step="0.0001"
                min="0"
                aria-label={t("Commission rate")}
                className={inputClass}
                value={commissionRate}
                onChange={(event) => setCommissionRate(event.target.value)}
              />
            </Field>
            <Field label="Minimum commission (¥)">
              <input
                type="number"
                step="1"
                min="0"
                aria-label={t("Minimum commission")}
                className={inputClass}
                value={minCommission}
                onChange={(event) => setMinCommission(event.target.value)}
              />
            </Field>
          </div>
          <Field label={t("Periods per year")} hint={t("Observational metadata for annualized descriptive statistics only.")}>
            <input
              type="number"
              step="1"
              min="1"
              aria-label={t("Periods per year")}
              className={inputClass}
              value={periodsPerYear}
              onChange={(event) => setPeriodsPerYear(event.target.value)}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Run window start (optional)">
              <input
                type="date"
                aria-label={t("Run window start")}
                className={inputClass}
                value={runStart}
                onChange={(event) => setRunStart(event.target.value)}
              />
            </Field>
            <Field label="Run window end (optional)">
              <input
                type="date"
                aria-label={t("Run window end")}
                className={inputClass}
                value={runEnd}
                onChange={(event) => setRunEnd(event.target.value)}
              />
            </Field>
          </div>
          <Button variant="secondary" className="w-full" onClick={() => setAdvancedOpen(false)}>
            {t("Done")}
          </Button>
        </div>
      </Drawer>
    </>
  );
}
