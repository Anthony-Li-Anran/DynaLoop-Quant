import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Pause,
  Play,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "../../components/ui/Button";
import type { BacktestBarFrame, BacktestFill, BacktestResult, PaneSpec } from "../api";
import { useTranslation } from "react-i18next";

/*
 * Panel layout follows kernc/backtesting.py -> backtesting/_plotting.py
 * (verified against upstream source): stacked panels share one x range
 * (new_indicator_figure(x_range=fig_ohlc.x_range), gridplot(ncols=1)), markers
 * sit off the price line, scale with |Size|, have a dark edge, and every
 * rendered series carries its own legend label.
 * Marker shape follows tradingview/lightweight-charts (verified against
 * src/plugins/series-markers/types.ts and website examples): SeriesMarkerShape
 * is 'circle' | 'square' | 'arrowUp' | 'arrowDown', with optional text, size
 * and position 'aboveBar' | 'belowBar' | 'inBar'. We use lettered circle
 * badges (B / S) below / above the bar instead of bare triangles.
 * Equity / position panels use ml4t-style per-bar portfolio_state snapshots.
 * Typography follows institutional quote pages: right-side numeric ticks, one
 * self-explanatory legend row per panel, and red-for-up / green-for-down for
 * all signed values.
 */

const C = {
  price: "#f1be67",
  equity: "#7dd3fc",
  benchmark: "#9aa0aa",
  position: "#c4b5fd",
  up: "#f87171",
  down: "#4ade80",
  grid: "#2f323a",
  axis: "#8b909b",
  ink: "#e6e8ec",
  muted: "#9497a0",
  edge: "#141518",
  cursor: "#e6e8ec",
};

const W = 960;
const PAD_L = 14;
const PAD_R = 78;
const PLOT_W = W - PAD_L - PAD_R;

const PRICE_H = 132;
const PRICE_TOP = 12;
const PRICE_BOTTOM = 112;
const EQUITY_H = 86;
const EQUITY_TOP = 10;
const EQUITY_BOTTOM = 68;
const POSITION_H = 66;
const POSITION_TOP = 8;
const POSITION_BOTTOM = 50;
const AXIS_H = 28;
const PANE_H = 88;
const PANE_TOP = 10;
const PANE_BOTTOM = 64;
const PANE_COLORS = ["#f1be67", "#7dd3fc", "#c4b5fd", "#fb923c", "#4ade80", "#9aa0aa"];

function paneColor(index: number): string {
  return PANE_COLORS[index % PANE_COLORS.length];
}

function yuan(value: number): string {
  return `¥${Number.isFinite(value) ? value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}`;
}

function quantity(value: number): string {
  return Number.isFinite(value)
    ? value.toLocaleString("en-US", { maximumFractionDigits: 2 })
    : "—";
}

function integer(value: number): string {
  return Number.isFinite(value) ? Math.round(value).toLocaleString("en-US") : "—";
}

function percent(value: number): string {
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function displayDate(timestamp: string): string {
  const value = (timestamp || "").trim();
  // Intraday stamps keep their time: "2026-11-10 14:35" and the compact
  // "202611101425" both render as "11-10 14:35"; session dates stay unchanged.
  if (/^\d{12}$/.test(value) || /^\d{8}[ T]\d{2}:?\d{2}/.test(value)) {
    const digits = value.replace(/\D/g, "");
    return `${digits.slice(4, 6)}-${digits.slice(6, 8)} ${digits.slice(8, 10)}:${digits.slice(10, 12)}`;
  }
  if (value.length > 10) return value.slice(5, 16);
  return value.slice(0, 10) || value;
}

type ReplayPlayerProps = {
  result: BacktestResult;
  symbol: string;
  onOpenDetails?: () => void;
  panes?: PaneSpec[];
  visiblePanes?: string[];
  onTogglePane?: (paneId: string) => void;
};

type TradeMark = {
  key: string;
  bar_index: number;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  count: number;
  timestamp: string;
};

type SwatchKind = "solid" | "dashed" | "area" | "badge-buy" | "badge-sell";

function SideBadge({ side, size = 16 }: { side: "buy" | "sell"; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center rounded-full font-bold leading-none"
      style={{
        width: size,
        height: size,
        fontSize: Math.max(9, size * 0.62),
        background: side === "buy" ? C.up : C.down,
        color: C.edge,
      }}
    >
      {side === "buy" ? "B" : "S"}
    </span>
  );
}

function Swatch({ kind, color }: { kind: SwatchKind; color: string }) {
  return (
    <svg width={16} height={10} viewBox="0 0 16 10" aria-hidden="true" className="shrink-0">
      {kind === "solid" && <line x1={0} y1={5} x2={16} y2={5} stroke={color} strokeWidth={2} />}
      {kind === "dashed" && (
        <line x1={0} y1={5} x2={16} y2={5} stroke={color} strokeWidth={2} strokeDasharray="4 3" />
      )}
      {kind === "area" && (
        <>
          <rect x={0} y={2} width={16} height={7} fill={color} fillOpacity={0.22} />
          <line x1={0} y1={2} x2={16} y2={2} stroke={color} strokeWidth={1.6} />
        </>
      )}
      {(kind === "badge-buy" || kind === "badge-sell") && (
        <>
          <circle cx={8} cy={5} r={4.2} fill={color} stroke={C.edge} strokeWidth={0.8} />
          <text
            x={8}
            y={7.3}
            textAnchor="middle"
            fontSize={6.5}
            fontWeight={700}
            fill={C.edge}
          >
            {kind === "badge-buy" ? "B" : "S"}
          </text>
        </>
      )}
    </svg>
  );
}

function LegendItem({
  label,
  value,
  kind,
  color,
}: {
  label: string;
  value?: string;
  kind: SwatchKind;
  color: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted">
      <Swatch kind={kind} color={color} />
      <span className="text-ink">{label}</span>
      {value !== undefined && <span className="font-mono tabular-nums">{value}</span>}
    </span>
  );
}

function PanelHeader({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-1">
      <span className="text-[11px] font-medium tracking-wide text-muted">{title}</span>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">{children}</div>
    </div>
  );
}

function YAxis({
  ticks,
  format,
}: {
  ticks: { value: number; y: number }[];
  format: (value: number) => string;
}) {
  return (
    <g aria-hidden="true">
      {ticks.map((tick, index) => (
        <g key={`tick-${index}`}>
          <line x1={PAD_L} x2={W - PAD_R} y1={tick.y} y2={tick.y} stroke={C.grid} strokeWidth={1} />
          <text
            x={W - PAD_R + 9}
            y={tick.y + 3.5}
            fill={C.axis}
            fontSize={10}
            fontFamily="ui-monospace, monospace"
          >
            {format(tick.value)}
          </text>
        </g>
      ))}
    </g>
  );
}

function Playhead({ x, height }: { x: number; height: number }) {
  return (
    <line
      x1={x}
      x2={x}
      y1={0}
      y2={height}
      stroke={C.cursor}
      strokeOpacity={0.32}
      strokeWidth={1}
      strokeDasharray="3 4"
      aria-hidden="true"
    />
  );
}

function formatPaneValue(value: number | null | undefined, format: string): string | undefined {
  if (value === null || value === undefined || !Number.isFinite(value)) return undefined;
  if (format === "currency") return yuan(value);
  if (format === "integer") return integer(value);
  if (format === "percent") return `${value.toFixed(2)}%`;
  return value.toFixed(3);
}

function seriesPath(
  values: (number | null | undefined)[],
  x: (index: number) => number,
  y: (value: number) => number,
): string {
  let path = "";
  let continuous = false;
  values.forEach((value, index) => {
    if (value === null || value === undefined || !Number.isFinite(value)) {
      continuous = false;
      return;
    }
    path += `${continuous ? "L" : "M"}${x(index).toFixed(2)},${y(value).toFixed(2)} `;
    continuous = true;
  });
  return path;
}

/**
 * Declaration-driven pane renderer. Every label, scale and series comes from
 * PaneSpec; nothing about a particular source or indicator is hard-coded here.
 * Panels share the caller's x mapping and playhead, following the stacked-pane
 * layout of backtesting.py / lightweight-charts.
 */
function PaneChart({
  pane,
  x,
  cursor,
  total,
}: {
  pane: PaneSpec;
  x: (index: number) => number;
  cursor: number;
  total: number;
}) {
  const observed = [
    ...pane.series
      .flatMap((series) => series.values)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    ...pane.reference_lines,
    0,
  ];
  const rawLow = Math.min(...observed);
  const rawHigh = Math.max(...observed);
  const pad = Math.max((rawHigh - rawLow) * 0.12, Math.abs(rawHigh) * 0.01, 0.001);
  const low = rawLow - pad;
  const high = rawHigh + pad;
  const y = (value: number) =>
    PANE_BOTTOM - ((value - low) / (high - low)) * (PANE_BOTTOM - PANE_TOP);
  const ticks = [0, 1, 2].map((step) => {
    const value = high - ((high - low) * step) / 2;
    return { value, y: PANE_TOP + ((PANE_BOTTOM - PANE_TOP) * step) / 2 };
  });
  const barWidth = Math.max(1.5, Math.min(9, (PLOT_W / Math.max(1, total)) * 0.6));

  return (
    <div className="space-y-1">
      <PanelHeader title={`${pane.label}${pane.unit ? ` (${pane.unit})` : ""}`}>
        {pane.series.map((series, index) => (
          <LegendItem
            key={`${pane.id}-${series.label}`}
            label={series.label}
            value={formatPaneValue(series.values[cursor], pane.format)}
            kind={series.style === "histogram" ? "area" : "solid"}
            color={paneColor(index)}
          />
        ))}
        {pane.warmup > 0 && (
          <span className="text-[10px] text-muted">
            First {pane.warmup} bars are not converged
          </span>
        )}
      </PanelHeader>
      <svg viewBox={`0 0 ${W} ${PANE_H}`} className="block w-full" aria-hidden="true">
        <YAxis ticks={ticks} format={(value) => formatPaneValue(value, pane.format) ?? "—"} />
        {pane.reference_lines.map((line) => (
          <line
            key={`reference-${line}`}
            x1={PAD_L}
            x2={W - PAD_R}
            y1={y(line)}
            y2={y(line)}
            stroke={C.grid}
            strokeWidth={1}
            strokeDasharray="4 4"
          />
        ))}
        {pane.series.map((series, index) => {
          const visible = series.values.slice(0, cursor + 1);
          const color = paneColor(index);
          if (series.style === "histogram") {
            return (
              <g key={`${pane.id}-${series.label}`} fill={color} fillOpacity={0.7}>
                {visible.map((value, barIndex) => {
                  if (value === null || value === undefined || !Number.isFinite(value)) return null;
                  const top = Math.min(y(value), y(0));
                  const bottom = Math.max(y(value), y(0));
                  return (
                    <rect
                      key={`bar-${barIndex}`}
                      x={x(barIndex) - barWidth / 2}
                      y={top}
                      width={barWidth}
                      height={Math.max(1, bottom - top)}
                    />
                  );
                })}
              </g>
            );
          }
          return (
            <path
              key={`${pane.id}-${series.label}`}
              d={seriesPath(visible, x, y)}
              fill="none"
              stroke={color}
              strokeWidth={1.6}
              strokeLinejoin="round"
            />
          );
        })}
        <Playhead x={x(cursor)} height={PANE_H} />
      </svg>
      {pane.definition && <p className="px-1 text-[10px] text-muted">{pane.definition}</p>}
    </div>
  );
}

export function ReplayPlayer({
  result,
  symbol,
  onOpenDetails,
  panes = [],
  visiblePanes = [],
  onTogglePane,
}: ReplayPlayerProps) {
  const { t } = useTranslation();
  const frames = useMemo<BacktestBarFrame[]>(() => {
    if (result.bars?.length) return result.bars;
    // Results stored before per-bar frames were emitted still carry complete
    // per-bar snapshots. Rebuild the tape from those marks so legacy runs
    // remain replayable without re-running the engine.
    return (result.portfolio_state ?? []).map((state) => ({
      timestamp: state.timestamp,
      bars: Object.fromEntries(
        Object.entries(state.marks ?? {}).map(([key, close]) => [
          key,
          {
            timestamp: state.timestamp,
            symbol: key,
            open: close,
            high: close,
            low: close,
            close,
            volume: 0,
          },
        ]),
      ),
    }));
  }, [result.bars, result.portfolio_state]);
  const states = useMemo(() => result.portfolio_state ?? [], [result]);
  const total = Math.min(frames.length, states.length);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [barsPerSecond, setBarsPerSecond] = useState(6);

  useEffect(() => {
    setCursor(0);
    setPlaying(false);
  }, [result]);

  useEffect(() => {
    if (!playing || total === 0) return;
    if (cursor >= total - 1) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(
      () => setCursor((value) => Math.min(value + 1, total - 1)),
      1000 / barsPerSecond,
    );
    return () => window.clearTimeout(timer);
  }, [playing, cursor, total, barsPerSecond]);

  const model = useMemo(() => {
    const positionSymbol = states.some((state) => state.positions?.[symbol] !== undefined)
      ? symbol
      : (result.spec.symbols[0] ?? symbol);
    const bars = frames.map((frame) => frame.bars?.[symbol]);
    const prices = bars.map((bar) => bar?.close ?? NaN);
    const opens = bars.map((bar) => bar?.open ?? NaN);
    const highs = bars.map((bar) => bar?.high ?? NaN);
    const lows = bars.map((bar) => bar?.low ?? NaN);
    const equities = states.map((state) => state.equity);
    const positions = states.map((state) => state.positions?.[positionSymbol] ?? 0);
    const benchmark = result.benchmark?.equity ?? [];

    // The price scale spans the full bar range, not just the close line.
    const validPrices = [...prices, ...opens, ...highs, ...lows].filter(Number.isFinite);
    const priceMin = validPrices.length ? Math.min(...validPrices) : 0;
    const priceMax = validPrices.length ? Math.max(...validPrices) : 1;
    const pricePad = Math.max((priceMax - priceMin) * 0.12, priceMax * 0.01, 0.01);
    const low = priceMin - pricePad;
    const high = priceMax + pricePad;

    const allEquity = [...equities, ...benchmark].filter(Number.isFinite);
    const eqMin = allEquity.length ? Math.min(...allEquity) : 0;
    const eqMax = allEquity.length ? Math.max(...allEquity) : 1;
    const eqPad = Math.max((eqMax - eqMin) * 0.12, 1);
    const eqLow = eqMin - eqPad;
    const eqHigh = eqMax + eqPad;

    const x = (index: number) =>
      PAD_L + (total <= 1 ? PLOT_W / 2 : (index / (total - 1)) * PLOT_W);
    const priceY = (value: number) =>
      PRICE_BOTTOM - ((value - low) / (high - low)) * (PRICE_BOTTOM - PRICE_TOP);
    const equityY = (value: number) =>
      EQUITY_BOTTOM - ((value - eqLow) / (eqHigh - eqLow)) * (EQUITY_BOTTOM - EQUITY_TOP);

    const path = (values: number[], toY: (value: number) => number) =>
      values
        .slice(0, cursor + 1)
        .map((value, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${toY(value).toFixed(2)}`)
        .join(" ");

    const posMax = Math.max(1, ...positions);
    const positionY = (value: number) =>
      POSITION_BOTTOM - (value / posMax) * (POSITION_BOTTOM - POSITION_TOP);
    const visiblePositions = positions.slice(0, cursor + 1);
    const positionPath = visiblePositions
      .map((value, index) => {
        const xp = x(index).toFixed(2);
        const yp = positionY(value).toFixed(2);
        if (index === 0) return `M${xp},${yp}`;
        return `L${xp},${positionY(visiblePositions[index - 1]).toFixed(2)} L${xp},${yp}`;
      })
      .join(" ");
    const positionArea =
      visiblePositions.length > 0
        ? `${positionPath} L${x(cursor).toFixed(2)},${POSITION_BOTTOM} L${x(0).toFixed(2)},${POSITION_BOTTOM} Z`
        : "";

    // One marker per (bar, side). backtesting.py scales markers by |Size|;
    // grouping keeps consecutive add/reduce fills from piling into one blob.
    const settled = (result.fills ?? []).filter(
      (fill) => fill.status !== "rejected" && fill.bar_index < total,
    );
    const grouped = new Map<string, TradeMark>();
    for (const fill of settled) {
      const side: "buy" | "sell" = fill.quantity > 0 ? "buy" : "sell";
      const key = `${fill.bar_index}:${side}`;
      const existing = grouped.get(key);
      if (existing) {
        existing.quantity += Math.abs(fill.quantity);
        existing.count += 1;
      } else {
        grouped.set(key, {
          key,
          bar_index: fill.bar_index,
          side,
          quantity: Math.abs(fill.quantity),
          price: fill.price,
          count: 1,
          timestamp: fill.timestamp,
        });
      }
    }
    const marks = [...grouped.values()].sort((a, b) => a.bar_index - b.bar_index);
    const maxMarkQuantity = Math.max(1, ...marks.map((mark) => mark.quantity));

    const priceTicks = [0, 1, 2, 3].map((step) => {
      const value = high - ((high - low) * step) / 3;
      return { value, y: PRICE_TOP + ((PRICE_BOTTOM - PRICE_TOP) * step) / 3 };
    });
    const equityTicks = [0, 1, 2].map((step) => {
      const value = eqHigh - ((eqHigh - eqLow) * step) / 2;
      return { value, y: EQUITY_TOP + ((EQUITY_BOTTOM - EQUITY_TOP) * step) / 2 };
    });
    const positionTicks = [posMax, 0].map((value) => ({ value, y: positionY(value) }));

    return {
      bars,
      prices,
      opens,
      highs,
      lows,
      equities,
      positions,
      positionSymbol,
      benchmark,
      posMax,
      x,
      priceY,
      equityY,
      positionY,
      equityPath: path(equities, equityY),
      benchmarkPath: path(benchmark, equityY),
      positionPath,
      positionArea,
      priceTicks,
      equityTicks,
      positionTicks,
      marks,
      maxMarkQuantity,
      visibleFills: settled.filter((fill) => fill.bar_index <= cursor),
      fillsAtCursor: settled.filter((fill) => fill.bar_index === cursor),
    };
  }, [frames, states, result.benchmark, result.fills, result.spec.symbols, symbol, cursor, total]);

  if (total === 0) {
    return (
      <div className="rounded-md border border-line bg-elevated/20 p-6 text-sm text-muted">
        {t("No bar-level market data in this run. Re-run the backtest from Setup to generate replay frames.")}
      </div>
    );
  }

  const current = states[cursor];
  const visibleSet = new Set(visiblePanes);
  // New runs declare only panes that can be drawn. Legacy runs may still
  // carry unavailable entries; those are simply skipped, never explained.
  const declaredPanes = panes.filter((pane) => pane.available !== false);
  const activePanes = declaredPanes.filter((pane) => visibleSet.has(pane.id));
  const separatePanes = activePanes.filter((pane) => pane.placement === "separate");
  const overlaySeries = activePanes
    .filter((pane) => pane.placement === "overlay")
    .flatMap((pane) =>
      pane.series.map((series, index) => ({ pane, series, color: paneColor(index) })),
    );
  const previous = cursor > 0 ? states[cursor - 1] : undefined;
  const activeSymbol = current?.positions?.[symbol] !== undefined ? symbol : (result.spec.symbols[0] ?? symbol);
  const positionNow = current?.positions?.[activeSymbol] ?? 0;
  const positionBefore = previous?.positions?.[activeSymbol] ?? 0;
  const positionDelta = positionNow - positionBefore;
  const markPrice = current?.marks?.[activeSymbol] ?? model.prices[cursor] ?? 0;
  const initialCash = result.metrics.initial_cash || 1;
  const runningReturn = (current?.equity ?? initialCash) / initialCash - 1;
  const timestamp = frames[cursor]?.timestamp ?? current?.timestamp ?? "—";
  const priceNow = model.prices[cursor];
  const priceBefore = cursor > 0 ? model.prices[cursor - 1] : NaN;
  const priceChange = Number.isFinite(priceNow) && Number.isFinite(priceBefore) ? priceNow - priceBefore : 0;
  const changeRatio = Number.isFinite(priceBefore) && priceBefore !== 0 ? priceChange / priceBefore : 0;
  const signedColor = (value: number) => (value > 0 ? C.up : value < 0 ? C.down : C.muted);
  const tickIndices = Array.from(
    new Set([0, Math.floor((total - 1) / 4), Math.floor((total - 1) / 2), Math.floor((3 * (total - 1)) / 4), total - 1]),
  );
  const hasBenchmark = model.benchmark.length > 0;
  const hasBuyMarks = model.marks.some((mark) => mark.side === "buy");
  const hasSellMarks = model.marks.some((mark) => mark.side === "sell");
  const visibleMarks = model.marks.filter((mark) => mark.bar_index <= cursor);
  const candleWidth = Math.max(1.5, Math.min(9, (PLOT_W / Math.max(1, total)) * 0.6));

  function jump(index: number) {
    setPlaying(false);
    setCursor(Math.max(0, Math.min(total - 1, index)));
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 border-b border-line pb-2">
        <span className="text-sm font-medium text-ink">{symbol}</span>
        <span className="text-[11px] text-muted">Close (CNY)</span>
        <span className="font-mono text-xl tabular-nums" style={{ color: signedColor(priceChange) }}>
          {Number.isFinite(priceNow) ? priceNow.toFixed(2) : "—"}
        </span>
        <span className="font-mono text-xs tabular-nums" style={{ color: signedColor(priceChange) }}>
          {cursor > 0 && Number.isFinite(priceBefore)
            ? `${priceChange >= 0 ? "+" : ""}${priceChange.toFixed(2)} (${percent(changeRatio)})`
            : "—"}
        </span>
        <span className="text-[11px] text-muted">
          {t("vs. previous bar · Cumulative")} <span style={{ color: signedColor(runningReturn) }}>{percent(runningReturn)}</span>
        </span>
        <span className="ml-auto font-mono text-[11px] text-muted">
          {displayDate(timestamp)} · Bar {cursor + 1} / {total}
        </span>
        {onOpenDetails && (
          <Button size="sm" variant="ghost" onClick={onOpenDetails}>
            {t("Run details")}
          </Button>
        )}
      </div>

      {declaredPanes.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-md border border-line/60 px-3 py-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted">{t("Panels")}</span>
          {declaredPanes.map((pane) => (
            <label
              key={pane.id}
              className="inline-flex items-center gap-1.5 text-xs text-ink"
              title={pane.definition ?? undefined}
            >
              <input
                type="checkbox"
                checked={visiblePanes.includes(pane.id)}
                onChange={() => onTogglePane?.(pane.id)}
                aria-label={`Toggle ${pane.label} pane`}
                className="accent-[rgb(var(--color-accent))]"
              />
              {pane.label}
            </label>
          ))}
        </div>
      )}

      <div
        className="mx-auto w-full max-w-4xl space-y-2 rounded-md border border-line bg-canvas/60 p-3"
        role="img"
        aria-label={t("Backtest replay: OHLC candles, trades, account equity and position")}
      >
        <PanelHeader title="Price · OHLC (CNY)">
          {[
            { label: "Open", value: model.opens[cursor], color: C.price },
            { label: "High", value: model.highs[cursor], color: C.up },
            { label: "Low", value: model.lows[cursor], color: C.down },
            { label: t("Close"), value: priceNow, color: C.price },
          ].map((item) => (
            <LegendItem
              key={item.label}
              label={item.label}
              value={Number.isFinite(item.value) ? item.value.toFixed(2) : undefined}
              kind="solid"
              color={item.color}
            />
          ))}
          <LegendItem label={t("Up bar")} kind="area" color={C.up} />
          <LegendItem label={t("Down bar")} kind="area" color={C.down} />
          {hasBuyMarks && <LegendItem label={t("Buy")} kind="badge-buy" color={C.up} />}
          {hasSellMarks && <LegendItem label={t("Sell")} kind="badge-sell" color={C.down} />}
          {overlaySeries.map(({ pane, series, color }) => (
            <LegendItem
              key={`${pane.id}-${series.label}`}
              label={series.label}
              value={formatPaneValue(series.values[cursor], pane.format)}
              kind="solid"
              color={color}
            />
          ))}
        </PanelHeader>
        <svg viewBox={`0 0 ${W} ${PRICE_H}`} className="block w-full" aria-hidden="true">
          <YAxis ticks={model.priceTicks} format={(value) => value.toFixed(2)} />
          {Array.from({ length: Math.min(cursor + 1, total) }, (_, index) => {
            const bar = model.bars[index];
            if (!bar) return null;
            const { open, high, low, close } = bar;
            if (![open, high, low, close].every(Number.isFinite)) return null;
            // Chinese market convention: rising bars red, falling bars green.
            const color = close >= open ? C.up : C.down;
            const x = model.x(index);
            const bodyTop = Math.min(model.priceY(open), model.priceY(close));
            const bodyBottom = Math.max(model.priceY(open), model.priceY(close));
            return (
              <g key={`candle-${index}`} data-testid={`candle-${index}`}>
                <line
                  x1={x}
                  x2={x}
                  y1={model.priceY(high)}
                  y2={model.priceY(low)}
                  stroke={color}
                  strokeWidth={1}
                />
                <rect
                  x={x - candleWidth / 2}
                  y={bodyTop}
                  width={candleWidth}
                  height={Math.max(1, bodyBottom - bodyTop)}
                  fill={color}
                  fillOpacity={0.85}
                  stroke={color}
                  strokeWidth={0.8}
                />
              </g>
            );
          })}
          {overlaySeries.map(({ pane, series, color }) => (
            <path
              key={`${pane.id}-${series.label}`}
              d={seriesPath(series.values.slice(0, cursor + 1), model.x, model.priceY)}
              fill="none"
              stroke={color}
              strokeWidth={1.5}
              strokeLinejoin="round"
            />
          ))}
          {visibleMarks.map((mark) => {
            const r = 6 + 1.8 * (mark.quantity / model.maxMarkQuantity) + (mark.bar_index === cursor ? 1 : 0);
            const px = model.x(mark.bar_index);
            const baseY = model.priceY(mark.price);
            const buy = mark.side === "buy";
            const py = buy
              ? Math.min(PRICE_BOTTOM - r - 1, baseY + 12 + r)
              : Math.max(PRICE_TOP + r + 1, baseY - 12 - r);
            const color = buy ? C.up : C.down;
            return (
              <g key={mark.key}>
                <title>{`${buy ? "Buy" : "Sell"} ${quantity(mark.quantity)} shares @ ${yuan(mark.price)} · ${displayDate(mark.timestamp)}${mark.count > 1 ? ` · ${mark.count} fills merged` : ""}`}</title>
                <line
                  x1={px}
                  x2={px}
                  y1={baseY}
                  y2={buy ? py - r : py + r}
                  stroke={color}
                  strokeOpacity={0.65}
                  strokeWidth={1}
                />
                <circle
                  cx={px}
                  cy={py}
                  r={r}
                  fill={color}
                  stroke={C.edge}
                  strokeWidth={mark.bar_index === cursor ? 1.6 : 1}
                />
                <text
                  x={px}
                  y={py + r * 0.36}
                  textAnchor="middle"
                  fontSize={r * 1.05}
                  fontWeight={700}
                  fill={C.edge}
                >
                  {buy ? "B" : "S"}
                </text>
              </g>
            );
          })}
          <Playhead x={model.x(cursor)} height={PRICE_H} />
        </svg>

        {separatePanes.map((pane) => (
          <PaneChart key={pane.id} pane={pane} x={model.x} cursor={cursor} total={total} />
        ))}

        <PanelHeader title="Equity (CNY)">
          <LegendItem
            label={t("Strategy equity")}
            value={integer(current?.equity ?? 0)}
            kind="solid"
            color={C.equity}
          />
          {hasBenchmark && (
            <LegendItem
              label={t("Buy & hold benchmark")}
              value={model.benchmark[cursor] !== undefined ? integer(model.benchmark[cursor]) : undefined}
              kind="dashed"
              color={C.benchmark}
            />
          )}
        </PanelHeader>
        <svg viewBox={`0 0 ${W} ${EQUITY_H}`} className="block w-full" aria-hidden="true">
          <YAxis ticks={model.equityTicks} format={(value) => integer(value)} />
          {hasBenchmark && (
            <path
              d={model.benchmarkPath}
              fill="none"
              stroke={C.benchmark}
              strokeWidth={1.5}
              strokeDasharray="5 4"
              strokeLinejoin="round"
            />
          )}
          <path d={model.equityPath} fill="none" stroke={C.equity} strokeWidth={1.8} strokeLinejoin="round" />
          <Playhead x={model.x(cursor)} height={EQUITY_H} />
        </svg>

        <PanelHeader title="Position (shares)">
          <LegendItem label={t("Position")} value={quantity(positionNow)} kind="area" color={C.position} />
        </PanelHeader>
        <svg viewBox={`0 0 ${W} ${POSITION_H}`} className="block w-full" aria-hidden="true">
          <YAxis ticks={model.positionTicks} format={(value) => integer(value)} />
          {model.positionArea && <path d={model.positionArea} fill={C.position} fillOpacity={0.16} stroke="none" />}
          <path d={model.positionPath} fill="none" stroke={C.position} strokeWidth={1.6} strokeLinejoin="round" />
          <Playhead x={model.x(cursor)} height={POSITION_H} />
        </svg>

        <svg viewBox={`0 0 ${W} ${AXIS_H}`} className="block w-full" aria-hidden="true">
          <line x1={PAD_L} x2={W - PAD_R} y1={2} y2={2} stroke={C.grid} strokeWidth={1} />
          {tickIndices.map((index) => (
            <text
              key={`axis-${index}`}
              x={model.x(index)}
              y={17}
              textAnchor="middle"
              fill={C.axis}
              fontSize={10}
              fontFamily="ui-monospace, monospace"
            >
              {displayDate(frames[index]?.timestamp ?? "")}
            </text>
          ))}
          <text x={PAD_L} y={26} fill={C.muted} fontSize={9}>
            {t("Timestamp")}
          </text>
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" aria-label={t("First bar")} onClick={() => jump(0)}>
          <ChevronsLeft className="h-4 w-4" />
        </Button>
        <Button size="sm" variant="secondary" aria-label={t("Previous bar")} onClick={() => jump(cursor - 1)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button
          size="sm"
          variant="primary"
          aria-label={playing ? "Pause replay" : "Play replay"}
          onClick={() => {
            if (cursor >= total - 1) setCursor(0);
            setPlaying((value) => !value);
          }}
        >
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          {playing ? "Pause" : "Play"}
        </Button>
        <Button size="sm" variant="secondary" aria-label={t("Next bar")} onClick={() => jump(cursor + 1)}>
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button size="sm" variant="secondary" aria-label={t("Last bar")} onClick={() => jump(total - 1)}>
          <ChevronsRight className="h-4 w-4" />
        </Button>
        <label className="ml-1 flex items-center gap-2 text-xs text-muted">
          {t("Replay speed")}
          <select
            aria-label={t("Replay speed")}
            value={barsPerSecond}
            onChange={(event) => setBarsPerSecond(Number(event.target.value))}
            className="min-h-8 rounded-md border border-line bg-canvas px-2 text-xs text-ink"
          >
            <option value={3}>0.5×</option>
            <option value={6}>1×</option>
            <option value={12}>2×</option>
            <option value={24}>4×</option>
          </select>
        </label>
        <span className="ml-auto font-mono text-xs text-muted">
          Bar {cursor + 1} / {total} · {displayDate(timestamp)}
        </span>
      </div>

      <input
        type="range"
        min={0}
        max={total - 1}
        value={cursor}
        aria-label={t("Replay progress")}
        onChange={(event) => jump(Number(event.target.value))}
        className="w-full accent-[rgb(var(--color-accent))]"
      />

      <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-5">
        <StateCard label="Cash (CNY)" value={yuan(current?.cash ?? 0)} />
        <StateCard
          label="Position (shares)"
          value={`${quantity(positionNow)} shares`}
          badge={
            Math.abs(positionDelta) > 1e-9
              ? { text: `${positionDelta > 0 ? "+" : "−"}${quantity(Math.abs(positionDelta))} shares`, positive: positionDelta > 0 }
              : undefined
          }
        />
        <StateCard label="Market value (CNY)" value={yuan(positionNow * markPrice)} />
        <StateCard label="Account equity (CNY)" value={yuan(current?.equity ?? 0)} />
        <StateCard
          label={t("Cumulative return")}
          value={percent(runningReturn)}
          tone={runningReturn >= 0 ? "up" : "down"}
        />
      </div>

      <div
        className={`rounded-md border px-4 py-2.5 text-sm ${
          model.fillsAtCursor.length
            ? "border-line bg-elevated/30"
            : "border-line/60 bg-transparent text-muted"
        }`}
        aria-live="polite"
      >
        {model.fillsAtCursor.length ? (
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            {model.fillsAtCursor.map((fill: BacktestFill) => (
              <span key={fill.fill_id} className="inline-flex items-center gap-2">
                <span style={{ color: fill.quantity > 0 ? C.up : C.down }} className="inline-flex items-center gap-1.5 font-semibold">
                  <SideBadge side={fill.quantity > 0 ? "buy" : "sell"} />
                  {fill.quantity > 0 ? "Buy" : "Sell"}
                </span>
                <span className="font-mono text-ink">
                  {quantity(Math.abs(fill.quantity))} shares @ {yuan(fill.price)}
                </span>
                <span className="text-xs text-muted">Fee {yuan(fill.commission)}</span>
              </span>
            ))}
          </div>
        ) : (
          <span>No fills on this bar · {model.visibleFills.length} fills so far</span>
        )}
      </div>

      {model.visibleFills.length > 0 && (
        <details className="rounded-md border border-line bg-elevated/10 px-3 py-2">
          <summary className="cursor-pointer text-xs text-muted">
            Fill ledger ({model.visibleFills.length} fills)
          </summary>
          <div className="scroll-panel mt-2" style={{ maxHeight: "8rem" }}>
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-muted">{t("No.")}</th>
                  <th className="px-3 py-2 text-left font-medium text-muted">{t("Trading date")}</th>
                  <th className="px-3 py-2 text-left font-medium text-muted">{t("Side")}</th>
                  <th className="px-3 py-2 text-right font-medium text-muted">Quantity (shares)</th>
                  <th className="px-3 py-2 text-right font-medium text-muted">Fill price (CNY)</th>
                  <th className="px-3 py-2 text-right font-medium text-muted">Fee (CNY)</th>
                </tr>
              </thead>
              <tbody>
                {model.visibleFills
                  .slice()
                  .reverse()
                  .slice(0, 6)
                  .map((fill) => (
                    <tr
                      key={fill.fill_id}
                      tabIndex={0}
                      role="button"
                      aria-label={`Jump to bar ${fill.bar_index + 1}`}
                      onClick={() => jump(fill.bar_index)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") jump(fill.bar_index);
                      }}
                      className={`cursor-pointer border-t border-line/60 hover:bg-elevated/40 ${
                        fill.bar_index === cursor ? "bg-elevated/30" : ""
                      }`}
                    >
                      <td className="px-3 py-1.5 font-mono text-muted">{fill.bar_index + 1}</td>
                      <td className="px-3 py-1.5 font-mono text-muted">{displayDate(fill.timestamp)}</td>
                      <td className="px-3 py-1.5" style={{ color: fill.quantity > 0 ? C.up : C.down }}>
                        <span className="inline-flex items-center gap-1.5">
                          <SideBadge side={fill.quantity > 0 ? "buy" : "sell"} size={14} />
                          {fill.quantity > 0 ? "Buy" : "Sell"}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-ink">{quantity(Math.abs(fill.quantity))}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-ink">{fill.price.toFixed(2)}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-ink">{fill.commission.toFixed(2)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function StateCard({
  label,
  value,
  badge,
  tone,
}: {
  label: string;
  value: string;
  badge?: { text: string; positive: boolean };
  tone?: "up" | "down";
}) {
  return (
    <div className="rounded-md border border-line bg-elevated/20 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[11px] text-muted">{label}</span>
        {badge && (
          <span
            className="rounded px-1.5 py-0.5 font-mono text-[10px]"
            style={{ color: badge.positive ? C.up : C.down, background: "rgb(43 44 48 / .8)" }}
            aria-label={badge.positive ? "Position increased" : "Position decreased"}
          >
            {badge.text}
          </span>
        )}
      </div>
      <div
        className="mt-1 font-mono text-base tabular-nums"
        style={{ color: tone === "up" ? C.up : tone === "down" ? C.down : undefined }}
      >
        {value}
      </div>
    </div>
  );
}
