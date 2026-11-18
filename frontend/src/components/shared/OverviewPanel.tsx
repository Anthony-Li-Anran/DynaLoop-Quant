import type { ReactNode } from "react";
import { ArrowUpRight, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Panel } from "./Panel";
import { MetricCard } from "./MetricCard";
import { useTranslation } from "react-i18next";

export function OverviewPanel({ title, to, children }: { title: string; to?: string; children: ReactNode }) {
  const { t } = useTranslation();
  return <Panel title={title} actions={to && <Link to={to} className="section-link">{t("View all")} <ArrowUpRight aria-hidden className="h-3.5 w-3.5" /></Link>}>{children}</Panel>;
}

export function OverviewMetric({ label, icon: Icon, value, note }: {
  label: string; icon: LucideIcon; value: number | undefined; note: string;
}) {
  return <MetricCard variant="strip" label={label} value={value === undefined ? "—" : value.toLocaleString()}
    icon={<Icon className="h-3.5 w-3.5" strokeWidth={1.6} />} note={value === undefined ? note : undefined} />;
}
