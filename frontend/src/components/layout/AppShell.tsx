import { useTranslation } from "react-i18next";
import { BRAND } from "../../app/brand";
import { Activity, Beaker, ChevronRight, Database, FileText, GitCompare, Home, Infinity, LineChart, MessageSquare, Repeat, Settings } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { LanguageSwitcher } from "../shared/LanguageSwitcher";

const navigation = [
  { to: "/", label: "Overview", icon: Home, end: true },
  { to: "/research", label: "Factor research", icon: Beaker },
  { to: "/evidence", label: "Evidence", icon: FileText },
  { to: "/subjective", label: "Subjective", icon: MessageSquare },
  { to: "/decision", label: "Decision", icon: GitCompare },
  { to: "/backtests", label: "Backtests", icon: LineChart },
  { to: "/experiments", label: "Experiments", icon: Beaker },
  { to: "/loop", label: "Loop", icon: Repeat },
  { to: "/data", label: "Data", icon: Database },
  { to: "/runtime", label: "Runtime", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppShell() {
  const location = useLocation();
  const { t } = useTranslation();
  const sectionLabel = t(
    navigation.find((item) => item.to === location.pathname)?.label ??
    (location.pathname.startsWith("/data")
      ? "Data"
      : location.pathname === "/components"
        ? "Component library"
        : "Overview"),
  );
  return (
    <div className="min-h-screen bg-canvas text-ink lg:grid lg:grid-cols-[212px_minmax(0,1fr)]">
      <aside className="relative flex flex-col border-b border-line bg-surface lg:sticky lg:top-0 lg:h-dvh lg:border-b-0 lg:border-r">
        <NavLink to="/" aria-label={`${BRAND.name} home`} className="flex h-14 shrink-0 items-center gap-2 px-5">
          <Infinity aria-hidden className="h-6 w-6 text-accent" strokeWidth={1.8} />
          <span className="text-[15px] font-semibold tracking-tight">{BRAND.name}</span>
        </NavLink>
        <p className="mb-2 mt-5 hidden px-5 text-[10px] font-medium uppercase tracking-[0.12em] text-muted/70 lg:block">{t("Workspace")}</p>
        <nav aria-label={t("Primary navigation")} className="flex gap-1 overflow-x-auto px-2 pb-2 lg:block lg:space-y-1 lg:px-2.5">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) =>
              `flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-[13px] transition-colors ${isActive ? "bg-elevated text-ink" : "text-muted hover:bg-elevated/50 hover:text-ink"}`}>
              {({ isActive }) => <><Icon aria-hidden className={`h-4 w-4 shrink-0 ${isActive ? "text-accent" : ""}`} strokeWidth={1.7} /><span>{t(label)}</span></>}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-5 py-4"><NavLink to="/components" className="mb-3 block text-xs text-muted hover:text-ink">{t("Component library")}</NavLink>
          <p className="text-[11px] text-muted">{t("AI × Quantitative Finance")}</p>
          <p className="mt-1 text-[10px] text-muted/60">{t("Research workspace")} · v0.1</p>
        </div>
      </aside>
      <div className="min-w-0">
        <header className="flex h-12 items-center justify-between gap-3 border-b border-line/60 px-5 lg:px-7">
          <div className="flex items-center gap-2 text-xs"><NavLink to="/" className="text-muted hover:text-ink">{t("Workspace")}</NavLink><ChevronRight aria-hidden className="h-3 w-3 text-muted/60" /><span>{sectionLabel}</span></div>
          <div className="flex items-center gap-3"><LanguageSwitcher /><span className="text-[11px] text-muted">{t("Local workspace")}</span></div>
        </header>
        <main className="mx-auto w-full max-w-[1320px] px-4 py-5 sm:px-6 lg:px-7"><Outlet /></main>
      </div>
    </div>
  );
}
