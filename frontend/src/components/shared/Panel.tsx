import { useId, type ReactNode } from "react";
import { SectionHeader } from "./PageHeader";

export function Panel({ title, description, actions, children, className = "" }: {
  title: string; description?: string; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  const headingId = useId();
  return <section aria-labelledby={headingId} className={`research-panel min-w-0 ${className}`}>
    <SectionHeader id={headingId} title={title} description={description} trailing={actions} />
    {children}
  </section>;
}
