import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "../components/shared/PageHeader";
import { Panel } from "../components/shared/Panel";
import { EmptyState, ErrorState, LoadingState } from "../components/shared/States";
import { Button } from "../components/ui/Button";
import { SelectField } from "../components/ui/SelectField";
import { api } from "../features/api";
import { CsvDataOverview } from "../features/data/components/CsvDataOverview";
import { useTranslation } from "react-i18next";

// Formats whose published bytes are columnar records rather than frozen bytes.
const RECORD_FORMATS = new Set(["csv", "kline-json"]);

export function DatasetPreviewPage() {
  const { t } = useTranslation();
  const { datasetId = "" } = useParams();
  const navigate = useNavigate();
  const [selectedVersion, setSelectedVersion] = useState<string>();
  const [missingPolicy, setMissingPolicy] = useState<"common" | "blank">("common");

  const datasets = useQuery({ queryKey: ["data", "datasets"], queryFn: api.datasets });
  const versions = useQuery({
    queryKey: ["data", "versions", datasetId],
    queryFn: () => api.versions(datasetId),
    enabled: Boolean(datasetId),
  });

  const dataset = datasets.data?.find((item) => item.dataset_id === datasetId);
  const versionId = selectedVersion ?? versions.data?.[0]?.version_id;
  // Only record-based datasets have a preview; raw-byte acquisitions are frozen as-is.
  const supportsPreview = Boolean(
    dataset?.format_id && RECORD_FORMATS.has(dataset.format_id),
  );
  const preview = useQuery({
    queryKey: ["data", "preview", missingPolicy, datasetId, versionId],
    queryFn: () => api.datasetPreview(datasetId, versionId!, "all", missingPolicy),
    enabled: Boolean(versionId) && supportsPreview,
  });

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={t("Data / Dataset preview")}
        title={dataset?.name ?? datasetId}
        description={datasetId}
        actions={
          <Button size="sm" onClick={() => navigate("/data?view=operations")}>
            <ArrowLeft aria-hidden className="mr-1.5 h-3.5 w-3.5" />
            {t("Back to data management")}
          </Button>
        }
      />

      {datasets.isLoading ? (
        <LoadingState />
      ) : datasets.error ? (
        <ErrorState title={t("Could not load datasets")} description={datasets.error.message} />
      ) : !dataset ? (
        <EmptyState
          title={t("Dataset not found")}
          description={`No dataset with ID '${datasetId}'.`}
        />
      ) : (
        <>
          <Panel
            title={t("Dataset")}
            description={`${dataset.data_type ?? "unspecified"} · ${dataset.format_id ?? "raw bytes"}`}
          >
            <dl className="grid gap-3 text-[13px] sm:grid-cols-2">
              <div>
                <dt className="text-muted">{t("Dataset ID")}</dt>
                <dd className="mt-1 break-all font-mono text-ink">{dataset.dataset_id}</dd>
              </div>
              <div>
                <dt className="text-muted">{t("Sources")}</dt>
                <dd className="mt-1 break-all font-mono text-ink">
                  {dataset.source_ids.join(", ") || "—"}
                </dd>
              </div>
            </dl>
            {versions.data && versions.data.length > 1 && (
              <div className="mt-4 max-w-sm">
                <SelectField
                  label={t("Version")}
                  value={versionId ?? ""}
                  onChange={(value) => setSelectedVersion(value)}
                  options={versions.data.map((version) => ({
                    value: version.version_id,
                    label: version.version_id,
                  }))}
                />
              </div>
            )}
          </Panel>

          {!supportsPreview ? (
            <EmptyState
              title={t("Preview not supported yet")}
              description={`'${dataset.name}' is stored as ${dataset.format_id ?? "raw bytes"}. Column preview is available for tabular datasets only; frozen bytes must be fetched as a table format first.`}
            />
          ) : !versionId ? (
            <EmptyState
              title={t("No published versions")}
              description={t("Fetch data from its source to publish the first version.")}
            />
          ) : (
            <Panel title={t("Preview")} description={`${datasetId} · ${versionId}`}>
              <div className="mb-4 max-w-md">
                <SelectField
                  label={t("Missing-value policy")}
                  value={missingPolicy}
                  onChange={(value) => setMissingPolicy(value as "common" | "blank")}
                  options={[
                    { value: "common", label: t("Blank + common markers") },
                    { value: "blank", label: t("Blank only (preserve NA and similar labels)") },
                  ]}
                  description="Changes preview statistics only; stored values remain unchanged."
                />
              </div>
              {preview.isLoading ? (
                <LoadingState />
              ) : preview.error ? (
                <ErrorState
                  title={t("Could not preview this dataset")}
                  description={preview.error.message}
                />
              ) : preview.data ? (
                <CsvDataOverview
                  preview={preview.data}
                  datasetId={datasetId}
                  versionId={versionId}
                />
              ) : null}
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
