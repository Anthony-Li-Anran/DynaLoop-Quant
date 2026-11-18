import { DetailPanel } from "../../../components/shared/DetailPanel";
import { TimeDisplay } from "../../../components/shared/Formatting";
import { StatusBadge } from "../../../components/shared/StatusBadge";
import type { QualityReport } from "../../api";
import { useTranslation } from "react-i18next";
export function QualityReportView({ activeQuality }: { activeQuality: QualityReport }) {
              const { t } = useTranslation(); return (<DetailPanel title={t("Quality findings")} description={`${activeQuality.rule_set_id} v${activeQuality.rule_set_version} · ${activeQuality.report_id}`}>
              <div className="mb-3 flex items-center justify-between">
                <span className="text-xs text-muted">{t("Checked")} <TimeDisplay value={activeQuality.checked_at} /></span>
                <StatusBadge status={activeQuality.status} />
              </div>
              {activeQuality.findings.length ? (
                <ul className="space-y-2 text-xs leading-5 text-muted">
                  {activeQuality.findings.map((finding, index) => <li key={`${index}:${finding}`} className="border-t border-line/70 pt-2">{finding}</li>)}
                </ul>
              ) : <p className="text-xs text-muted">{t("No findings recorded.")}</p>}
            </DetailPanel>); }
