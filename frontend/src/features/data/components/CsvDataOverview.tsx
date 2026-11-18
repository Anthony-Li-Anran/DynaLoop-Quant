import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { MetricCard } from "../../../components/shared/MetricCard";
import { DataTable, type Column } from "../../../components/shared/DataTable";
import { SelectField } from "../../../components/ui/SelectField";
import { ColumnVisualization } from "./ColumnVisualization";
import type { CsvColumnSummary, CsvPreview } from "../../api";
import { useTranslation } from "react-i18next";

function formatStatistic(value: number | string | null): string {
  if (value === null) return "—";
  if (typeof value === "string") return value;
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 6 }).format(value);
}

type SectionKey = "profile" | "sample" | "visualization";

function AccordionSection({
  id,
  title,
  meta,
  open,
  onToggle,
  children,
}: {
  id: string;
  title: string;
  meta?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-line first:border-t-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`csv-overview-${id}`}
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-3 py-3.5 text-left transition-colors hover:bg-elevated/25"
      >
        <span className="flex items-center gap-2 text-base font-semibold tracking-[0.01em] text-ink">
          <ChevronRight
            aria-hidden
            className={`h-4 w-4 text-muted transition-transform duration-150 ${open ? "rotate-90" : ""}`}
          />
          {title}
        </span>
        {meta && (
          <span className="font-mono text-xs text-muted">{meta}</span>
        )}
      </button>
      {open && (
        <div id={`csv-overview-${id}`} className="px-3 pb-5">
          {children}
        </div>
      )}
    </div>
  );
}

export function CsvDataOverview({
  preview,
  datasetId,
  versionId,
}: {
  preview: CsvPreview;
  datasetId: string;
  versionId: string;
}) {
  const { t } = useTranslation();
  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>({
    profile: true,
    sample: false,
    visualization: false,
  });
  const [selectedColumn, setSelectedColumn] = useState<string>();
  const toggleSection = (key: SectionKey) =>
    setOpenSections((previous) => ({ ...previous, [key]: !previous[key] }));
  const missingValues = preview.columns.reduce(
    (total, column) => total + column.missing_count,
    0,
  );
  const columns: Column<CsvColumnSummary>[] = [
    { key: "name", header: "Column", render: (column) => <span className="font-medium text-ink">{column.name}</span> },
    { key: "type", header: "Detected type", render: (column) => column.inferred_type },
    { key: "observed", header: "Values", render: (column) => column.observed_count },
    { key: "missing", header: "Missing", render: (column) => column.missing_count },
    { key: "distinct", header: "Distinct", render: column => column.distinct_count },
    { key: "top", header: "Top values", render: column => <span className="block max-w-64 break-words">{column.top_values.map(([value, count]) => `${value} (${count})`).join(" · ")}</span> },
    { key: "notes", header: "Notes", render: column => <span className="block max-w-48 text-muted">{column.notes.join(" ") || "—"}</span> },
    { key: "minimum", header: "Min", render: (column) => formatStatistic(column.minimum) },
    { key: "mean", header: "Mean", render: (column) => formatStatistic(column.mean) },
    { key: "deviation", header: "Std dev", render: (column) => formatStatistic(column.standard_deviation) },
    { key: "maximum", header: "Max", render: (column) => formatStatistic(column.maximum) },
  ];

  return (
    <section aria-label={t("CSV data overview")} className="grid gap-5">
      <div>
        <h3 className="text-base font-semibold text-ink">{t("Dataset preview")}</h3>
        <p className="mt-1 text-[13px] text-muted">
          Statistics cover the selected published partition; each section expands in place.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2"><MetricCard label={t("Rows")} value={preview.row_count.toLocaleString()} /><MetricCard label={t("Columns")} value={preview.columns.length} /><MetricCard label={t("Missing values")} value={missingValues.toLocaleString()} /></div>

      <div className="min-w-0 rounded-panel border border-line">
        <AccordionSection
          id="profile"
          title={t("Column profile")}
          meta={`${preview.columns.length} columns`}
          open={openSections.profile}
          onToggle={() => toggleSection("profile")}
        >
          <div className="scroll-panel">
            <DataTable
              rows={preview.columns}
              columns={columns}
              getRowKey={(column) => column.name}
              onRowClick={(column) => {
                setSelectedColumn(column.name);
                setOpenSections((previous) => ({ ...previous, visualization: true }));
              }}
            />
          </div>
          <p className="mt-2 text-xs leading-4 text-muted">
            Types are inferred, not schema guarantees. {preview.missing_policy === "blank" ? "Only empty or whitespace cells are missing." : "Empty cells, ., NA, N/A, NaN, null and none are missing (case-insensitive)."} Category counts preserve original text; unknown and numeric sentinel values remain observed. Std dev uses n − 1. Click a row to visualize that column.
          </p>
        </AccordionSection>

        <AccordionSection
          id="sample"
          title={t("Sample rows")}
          meta={`${preview.preview_rows.length} of ${preview.row_count.toLocaleString()}`}
          open={openSections.sample}
          onToggle={() => toggleSection("sample")}
        >
          {preview.preview_rows.length === 0 ? (
            <p className="rounded-md border border-line px-3 py-4 text-[13px] text-muted">
              {t("This published dataset contains no records to preview.")}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-md border border-line">
              <table className="w-full min-w-max border-collapse text-left text-[13px]">
                <thead>
                  <tr className="border-b border-line bg-elevated/60">
                    {preview.columns.map((column, index) => (
                      <th key={`${column.name}-${index}`} scope="col" className="px-3 py-2 font-medium text-muted">
                        {column.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/70">
                  {preview.preview_rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {preview.columns.map((column, columnIndex) => (
                        <td key={`${column.name}-${columnIndex}`} className="whitespace-nowrap px-3 py-2 text-ink">
                          {row[columnIndex] ?? <span className="text-muted">—</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {preview.preview_truncated && (
            <p className="mt-2 text-xs text-muted">{t("Showing the first 5 rows.")}</p>
          )}
        </AccordionSection>

        <AccordionSection
          id="visualization"
          title={t("Visualization")}
          meta={selectedColumn}
          open={openSections.visualization}
          onToggle={() => toggleSection("visualization")}
        >
          <div className="grid gap-3">
            <div className="max-w-md">
              <SelectField
                label={t("Column")}
                value={selectedColumn ?? ""}
                onChange={(value) => setSelectedColumn(value || undefined)}
                options={[
                  { value: "", label: t("Select a column") },
                  ...preview.columns.map((column) => ({ value: column.name, label: column.name })),
                ]}
              />
            </div>
            <ColumnVisualization
              datasetId={datasetId}
              versionId={versionId}
              column={selectedColumn}
            />
          </div>
        </AccordionSection>
      </div>
    </section>
  );
}
