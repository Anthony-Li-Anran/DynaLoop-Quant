import { DetailPanel } from "../../../components/shared/DetailPanel";
import { ByteSize } from "../../../components/shared/Formatting";
import type { DatasetVersion } from "../../api";
import { useTranslation } from "react-i18next";
export function PartitionList({ versions }: { versions: DatasetVersion[] }) {
            const { t } = useTranslation(); return (<div className="mt-4"><DetailPanel title={t("Partition inventory")} description={t("Content references for published versions.")}>
            <div className="space-y-3">
              {versions.flatMap((version) =>
                version.partitions.map((partition) => (
                  <div key={`${version.version_id}:${partition.partition_id}`} className="grid gap-2 border-t border-line/70 pt-3 text-xs sm:grid-cols-[1.3fr_1fr_0.6fr_1fr]">
                    <span className="font-mono text-ink">{version.version_id} / {partition.partition_id}</span>
                    <span className="text-muted">{partition.partition_values.map(([key, value]) => `${key}=${value}`).join(" · ") || "No logical keys"}</span>
                    <span className="text-muted">{partition.record_count ?? "—"} records</span>
                    <span className="truncate font-mono text-muted" title={partition.content_reference?.content_hash}>{partition.content_reference ? <>{partition.content_reference.hash_algorithm}:{partition.content_reference.content_hash.slice(0, 14)}… · <ByteSize value={partition.content_reference.size_bytes} /></> : "No content reference"}</span>
                  </div>
                )),
              )}
            </div>
          </DetailPanel></div>); }