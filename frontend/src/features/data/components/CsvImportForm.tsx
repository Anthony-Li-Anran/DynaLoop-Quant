import { SelectField } from "../../../components/ui/SelectField";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ErrorState } from "../../../components/shared/States";
import { Button } from "../../../components/ui/Button";
import { api, type CsvImportResult, type QualityPolicy } from "../../api";
import { useTranslation } from "react-i18next";

type CsvImportFormProps = {
  onImported: (result: CsvImportResult) => void;
};

const fieldClassName =
  "mt-1 min-h-10 w-full rounded-md border border-line bg-canvas px-3 text-sm text-ink placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

function filenameStem(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, "") || fileName;
}

function datasetIdFromFilename(fileName: string): string {
  return filenameStem(fileName)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "dataset";
}

export function CsvImportForm({ onImported }: CsvImportFormProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [datasetId, setDatasetId] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [file, setFile] = useState<File>();
  const [encoding, setEncoding] = useState("auto");
  const [delimiter, setDelimiter] = useState("auto");
  const [qualityPolicy, setQualityPolicy] = useState<QualityPolicy>("gate_on_fail");
  const mutation = useMutation({
    mutationFn: api.importCsv,
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["data", "sources"] }),
        queryClient.invalidateQueries({ queryKey: ["data", "datasets"] }),
        queryClient.invalidateQueries({
          queryKey: ["data", "versions", result.dataset_id],
        }),
      ]);
      onImported(result);
    },
  });

  function selectFile(selected: File | undefined) {
    setFile(selected);
    mutation.reset();
    if (!selected) {
      setDatasetId("");
      setDatasetName("");
      return;
    }

    setDatasetId(datasetIdFromFilename(selected.name));
    setDatasetName(filenameStem(selected.name));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    mutation.mutate({ datasetId, datasetName, file, encoding, delimiter, qualityPolicy });
  }

  return (
    <form className="grid gap-4" onSubmit={submit}>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="text-xs font-medium text-ink">
          {t("Dataset name")}
          <input
            className={fieldClassName}
            name="dataset_name"
            placeholder={t("Name shown in the catalog")}
            value={datasetName}
            onChange={(event) => setDatasetName(event.target.value)}
            required
          />
          <span className="mt-1 block font-normal text-muted">
            {t("Filled from the filename. You can change it.")}
          </span>
        </label>
        <label className="text-xs font-medium text-ink">
          {t("Dataset ID")}
          <input
            className={fieldClassName}
            name="dataset_id"
            autoComplete="off"
            placeholder={t("generated-from-filename")}
            value={datasetId}
            onChange={(event) => setDatasetId(event.target.value)}
            required
          />
          <span className="mt-1 block font-normal leading-4 text-muted">
            {t("Stable identifier from the filename. Reusing it for the same dataset adds a version.")}
          </span>
        </label>
        <label className="text-xs font-medium text-ink md:col-span-2">
          {t("CSV file")}
          <input
            className={`${fieldClassName} file:mr-3 file:border-0 file:bg-transparent file:text-xs file:font-medium file:text-accent`}
            name="file"
            type="file"
            aria-label={t("CSV file")}
            accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values"
            onChange={(event) => selectFile(event.target.files?.[0])}
            required
          />
          <span className="mt-1 block font-normal text-muted">
            CSV/TSV with a unique header row; maximum size 10 MiB. Original cell text is preserved.
          </span>
        </label>
        <SelectField label={t("Encoding")} value={encoding} onChange={setEncoding} disabled={mutation.isPending} options={[{value:"auto",label: t("Auto (UTF-8 / BOM)")},{value:"utf-8-sig",label: t("UTF-8")},{value:"utf-16",label: t("UTF-16 (BOM)")},{value:"gb18030",label: t("GB18030 / GBK")},{value:"cp1252",label: t("Windows-1252")}]} description={t("For legacy files, select their encoding explicitly.")} />
        <SelectField label={t("Delimiter")} value={delimiter} onChange={setDelimiter} disabled={mutation.isPending} options={[{value:"auto",label:"Auto"},{value:",",label:"Comma"},{value:";",label:"Semicolon"},{value:"\t",label:"Tab"},{value:"|",label:"Pipe"}]} description={t("If auto-detection is ambiguous, select the separator used by the file.")} />
        <SelectField label={t("Quality policy")} value={qualityPolicy} onChange={(value) => setQualityPolicy(value as QualityPolicy)} disabled={mutation.isPending} options={[{value:"gate_on_fail",label: t("Gate on FAIL (retract version)")},{value:"report_only",label: t("Report only (always publish)")}]} description="Gate runs schema/integrity checks after publishing; a FAIL retracts the version and restores the previous one." />
      </div>
      <div className="flex flex-col items-start gap-3 border-t border-line pt-4 sm:flex-row sm:items-center">
        <Button type="submit" disabled={!file || mutation.isPending}>
          {mutation.isPending ? "Importing…" : "Import data"}
        </Button>
        {mutation.error && (
          <ErrorState
            title={t("CSV import failed")}
            description={mutation.error.message}
          />
        )}
      </div>
    </form>
  );
}
