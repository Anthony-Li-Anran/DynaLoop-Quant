import { DetailPanel } from "../../../components/shared/DetailPanel";
import type { DatasetSnapshot } from "../../api";
import { useTranslation } from "react-i18next";
export function SnapshotView({ activeSnapshot }: { activeSnapshot: DatasetSnapshot }) {
              const { t } = useTranslation(); return (<DetailPanel title={`Snapshot ${activeSnapshot.snapshot_id}`} description={t("Explicit partition source map")}>
              <div className="space-y-3">
                {activeSnapshot.partition_sources.map((source, index) => (
                  <div key={`${source.dataset_id}:${index}`} className="grid gap-1 border-b border-line/70 pb-3 last:border-0 last:pb-0 sm:grid-cols-3">
                    <span className="font-mono text-xs text-ink">{source.dataset_id} · {source.partition_values.map(([key, value]) => `${key}=${value}`).join(", ")}</span>
                    <span className="font-mono text-xs text-muted">{source.source_version.dataset_id}@{source.source_version.version_id}</span>
                    <span className="font-mono text-xs text-muted">partition {source.partition_id}</span>
                  </div>
                ))}
                {activeSnapshot.partition_sources.length === 0 && <p className="text-xs text-muted">{t("This Snapshot has no partition mappings.")}</p>}
              </div>
            </DetailPanel>); }
