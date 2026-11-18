import { useQuery } from "@tanstack/react-query";
import { DetailPanel, MetadataList } from "../components/shared/DetailPanel";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/States";
import { Badge } from "../components/ui/Badge";
import { api } from "../features/api";
import { useTranslation } from "react-i18next";

export function SettingsPage() {
  const { t } = useTranslation();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  return (
    <>
      <PageHeader eyebrow={t("Workspace / Configuration")} title={t("Settings")} description={t("Current settings exposed by the existing Infrastructure configuration API. This page does not create or edit configuration.")} />
      <QueryState query={settings} emptyTitle={t("Configuration unavailable")}>
        {(current) => (
          <div className="max-w-2xl">
            <DetailPanel title={t("Application configuration")} description={t("Resolved settings from configured TOML and environment overrides.")}>
              <MetadataList
                items={[
                  { label: t("Logging level"), value: <Badge>{current.log_level}</Badge> },
                  { label: "Source", value: "Infrastructure Settings" },
                  { label: t("Editable here"), value: "No" },
                ]}
              />
            </DetailPanel>
          </div>
        )}
      </QueryState>
    </>
  );
}
