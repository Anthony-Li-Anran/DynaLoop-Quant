
import { useTranslation } from "react-i18next";export function TimeDisplay({ value }: { value?: string | null }) {
  if (!value) return <span className="text-muted">—</span>;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return <span className="font-mono text-xs">{value}</span>;
  return (
    <time dateTime={value} title={date.toLocaleString()} className="font-mono text-xs text-muted">
      {date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
    </time>
  );
}

export function MetricDisplay({
  value,
  label,
}: {
  value: number | null;
  label?: string;
}) {
  return (
    <span className="inline-flex flex-col gap-1">
      {label && <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>}
      <span className="font-mono text-sm tabular-nums text-ink">
        {value === null ? "Unavailable" : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value)}
      </span>
    </span>
  );
}

export function ByteSize({ value }: { value: number | null }) {
  const { t } = useTranslation();
  if (value === null) return <span className="text-muted">{t("Unavailable")}</span>;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return <span className="font-mono text-xs tabular-nums">{`${size.toFixed(unitIndex ? 1 : 0)} ${units[unitIndex]}`}</span>;
}
