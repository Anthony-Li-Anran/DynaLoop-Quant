import type { ReactNode } from "react";

export function MetricCard({ label, value, icon, note, variant = "card" }: {
  label: string; value: ReactNode; icon?: ReactNode; note?: string; variant?: "card" | "strip";
}) {
  return <section className={`metric-card metric-card--${variant}`}>
    <div className="flex items-center justify-between gap-2">
      <h2 className="text-[13px] text-muted">{label}</h2>
      {icon && <span aria-hidden className="text-muted">{icon}</span>}
    </div>
    <div className="metric-value">{value}</div>
    {note && <p className="mt-1 text-xs leading-4 text-muted">{note}</p>}
  </section>;
}
