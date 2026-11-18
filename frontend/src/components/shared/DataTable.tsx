import type { ReactNode } from "react";
import { EmptyState } from "./States";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
}

export function DataTable<T>({
  rows,
  columns,
  getRowKey,
  onRowClick,
  emptyTitle = "No records",
  emptyDescription = "Records will appear here when available from the connected module.",
}: {
  rows: T[];
  columns: Column<T>[];
  getRowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }
  return (
    <div className="data-table overflow-x-auto rounded-panel border border-line">
      <table className="w-full min-w-[400px] border-collapse text-left">
        <thead>
          <tr className="border-b border-line bg-elevated/60">
            {columns.map((column) => (
              <th scope="col"
                key={column.key}
                className={`px-3 py-2 text-[13px] font-medium text-muted ${column.className ?? ""}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/70">
          {rows.map((row) => (
            <tr
              key={getRowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              aria-label={onRowClick ? `Select ${getRowKey(row)}` : undefined}
              onKeyDown={onRowClick ? (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onRowClick(row); } } : undefined}
              className={onRowClick ? "cursor-pointer transition-colors hover:bg-elevated/50" : ""}
            >
              {columns.map((column) => (
                <td key={column.key} className={`px-3 py-2.5 align-top text-[13px] ${column.className ?? ""}`}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
