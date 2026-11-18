import { RuntimeInfoPanel } from "../features/runtime/components/RuntimeInfoPanel";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/States";
import { api } from "../features/api";
import { useTranslation } from "react-i18next";
export function RuntimePage() {
  const { t } = useTranslation();
  const runtime = useQuery({ queryKey: ["runtime"], queryFn: api.runtime });
  return (
    <>
      <PageHeader eyebrow={t("Infrastructure / Host")} title={t("Runtime")} description={t("Read-only Python and host resource information reported by the active API process.")} />
      <QueryState query={runtime} emptyTitle={t("Runtime information unavailable")}>
        {(payload) => <RuntimeInfoPanel payload={payload} />}
      </QueryState>
    </>
  );
}

