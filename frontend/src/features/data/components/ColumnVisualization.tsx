import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../../api";
import { ErrorState, LoadingState } from "../../../components/shared/States";
import { useTranslation } from "react-i18next";

// Fixed dark-theme chart palette (matches src/styles/index.css tokens).
const AXIS_COLOR = "#9497a0";
const BAR_COLOR = "#f1be67";
const GRID_COLOR = "rgba(148, 151, 160, 0.15)";
const TOOLTIP_STYLE: React.CSSProperties = {
  background: "#141518",
  border: "1px solid #313237",
  borderRadius: 8,
  fontSize: 12,
};

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 }).format(value);
}

function formatBinEdge(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 }).format(value);
}

export function ColumnVisualization({
  datasetId,
  versionId,
  column,
}: {
  datasetId: string;
  versionId: string;
  column: string | undefined;
}) {
  const { t } = useTranslation();
  const distribution = useQuery({
    queryKey: ["data", "distribution", datasetId, versionId, column],
    queryFn: () => api.columnDistribution(datasetId, versionId, column!),
    enabled: Boolean(column),
  });

  if (!column) {
    return (
      <p className="rounded-md border border-line px-3 py-6 text-center text-[13px] text-muted">
        {t("Select a column in Column profile above to visualize its distribution.")}
      </p>
    );
  }
  if (distribution.isLoading) {
    return <LoadingState />;
  }
  if (distribution.error) {
    return <ErrorState title={t("Could not compute the distribution")} description={distribution.error.message} />;
  }
  const data = distribution.data;
  if (!data) return null;

  if (data.kind === "empty") {
    return (
      <p className="rounded-md border border-line px-3 py-6 text-center text-[13px] text-muted">
        Column "{column}" has no observed values to chart.
      </p>
    );
  }

  if (data.kind === "histogram") {
    const meanBinLabel =
      data.mean === null
        ? undefined
        : data.bins.find((bin) => bin.lower <= data.mean! && data.mean! <= bin.upper);
    const chartData = data.bins.map((bin, index) => ({
      label:
        index === data.bins.length - 1
          ? `[${formatBinEdge(bin.lower)}, ${formatBinEdge(bin.upper)}]`
          : `[${formatBinEdge(bin.lower)}, ${formatBinEdge(bin.upper)})`,
      count: bin.count,
    }));
    return (
      <div className="grid gap-2">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: AXIS_COLOR, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: GRID_COLOR }}
              minTickGap={24}
            />
            <YAxis
              tick={{ fill: AXIS_COLOR, fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
              width={44}
            />
            <Tooltip
              cursor={{ fill: "rgba(148, 151, 160, 0.08)" }}
              contentStyle={TOOLTIP_STYLE}
              labelStyle={{ color: "#e6e7e9" }}
              itemStyle={{ color: "#e6e7e9" }}
            />
            <Bar dataKey="count" fill={BAR_COLOR} radius={[3, 3, 0, 0]} maxBarSize={72} />
            {meanBinLabel && (
              <ReferenceLine
                x={chartData[data.bins.indexOf(meanBinLabel)].label}
                stroke={AXIS_COLOR}
                strokeDasharray="4 4"
                label={{ value: "mean", position: "insideTopRight", fill: AXIS_COLOR, fontSize: 11 }}
              />
            )}
          </BarChart>
        </ResponsiveContainer>
        <p className="text-xs text-muted">
          {data.rule} · observed {data.observed_count.toLocaleString()} · missing{" "}
          {data.missing_count.toLocaleString()} · mean {data.mean === null ? "—" : formatNumber(data.mean)}
        </p>
      </div>
    );
  }

  const chartData = [
    ...data.categories.map((item) => ({ label: item.value, count: item.count })),
    ...(data.other_count > 0 ? [{ label: "(other)", count: data.other_count }] : []),
  ];
  return (
    <div className="grid gap-2">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: AXIS_COLOR, fontSize: 12 }}
            tickLine={false}
            axisLine={{ stroke: GRID_COLOR }}
            minTickGap={16}
            interval={0}
            angle={-30}
            textAnchor="end"
            height={70}
          />
          <YAxis
            tick={{ fill: AXIS_COLOR, fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            width={44}
          />
          <Tooltip
            cursor={{ fill: "rgba(148, 151, 160, 0.08)" }}
            contentStyle={TOOLTIP_STYLE}
            labelStyle={{ color: "#e6e7e9" }}
            itemStyle={{ color: "#e6e7e9" }}
          />
          <Bar dataKey="count" fill={BAR_COLOR} radius={[3, 3, 0, 0]} maxBarSize={72}>
            {chartData.map((item, index) => (
              <Cell key={item.label} fill={item.label === "(other)" ? "#6b6e77" : BAR_COLOR} fillOpacity={1 - index * 0.04} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-muted">
        {data.rule} · observed {data.observed_count.toLocaleString()} · missing{" "}
        {data.missing_count.toLocaleString()}
        {data.other_count > 0 ? ` · ${data.other_count.toLocaleString()} in (other)` : ""}
      </p>
    </div>
  );
}
