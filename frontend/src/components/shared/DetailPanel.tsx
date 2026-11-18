import type { ReactNode } from "react";
export { Panel as DetailPanel } from "./Panel";

export function MetadataList({
  items,
}: {
  items: { label: string; value: ReactNode }[];
}) {
  return (
    <dl className="divide-y divide-line/70">
      {items.map((item) => (
        <div key={item.label} className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[150px_1fr] sm:gap-4">
          <dt className="text-xs text-muted">{item.label}</dt>
          <dd className="break-all text-sm text-ink">{item.value ?? <span className="text-muted">—</span>}</dd>
        </div>
      ))}
    </dl>
  );
}
