import { Cpu, HardDrive } from "lucide-react";
import { BRAND } from "../../../app/brand";
import { Panel } from "../../../components/shared/Panel";
import { MetadataList } from "../../../components/shared/DetailPanel";
import { ByteSize, TimeDisplay } from "../../../components/shared/Formatting";
import { MetricCard } from "../../../components/shared/MetricCard";
import type { RuntimePayload } from "../../api";
import { useTranslation } from "react-i18next";

export function RuntimeInfoPanel({ payload: { runtime, resources } }: { payload: RuntimePayload }) {
  const { t } = useTranslation();
  return <div className="grid gap-4 lg:grid-cols-2">
    <Panel title={t("Python environment")} description={`${BRAND.name} · ${runtime.project_version ?? "Version unavailable"}`}>
      <MetadataList items={[{ label: "Python", value: runtime.python_version }, { label: "Interpreter", value: runtime.python_executable }, { label: t("Operating system"), value: runtime.os_name }, { label: "Platform", value: runtime.platform }]} />
    </Panel>
    <Panel title={t("Host resources")} description={t("Physical memory and CPU availability at the time of this request.")}>
      <div className="grid grid-cols-2 gap-3">
        <MetricCard icon={<Cpu className="h-4 w-4" />} label={t("Logical CPUs")} value={resources.cpu_logical_count ?? "—"} />
        <MetricCard icon={<Cpu className="h-4 w-4" />} label={t("Available CPUs")} value={resources.cpu_available_count ?? "—"} />
        <MetricCard icon={<HardDrive className="h-4 w-4" />} label={t("Total memory")} value={<ByteSize value={resources.memory_total_bytes} />} />
        <MetricCard icon={<HardDrive className="h-4 w-4" />} label={t("Available memory")} value={<ByteSize value={resources.memory_available_bytes} />} />
      </div>
      <p className="mt-3 text-xs text-muted">{t("Captured")} <TimeDisplay value={resources.captured_at} /></p>
    </Panel>
  </div>;
}
