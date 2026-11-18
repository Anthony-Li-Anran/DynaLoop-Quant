import type { ReactNode } from "react";

export function PageHeader({ eyebrow, title, description, actions }: {
  eyebrow: string; title: string; description?: string; actions?: ReactNode;
}) {
  return <header className="page-heading">
    <div className="min-w-0 max-w-3xl">
      <p className="page-eyebrow">{eyebrow}</p>
      <h1 className="page-title">{title}</h1>
      {description && <p className="page-description">{description}</p>}
    </div>{actions}
  </header>;
}

export function SectionHeader({ id, title, description, trailing }: {
  id?: string; title: string; description?: string; trailing?: ReactNode;
}) {
  return <div className="section-heading">
    <div className="min-w-0"><h2 id={id} className="section-title">{title}</h2>
      {description && <p className="mt-1 text-[13px] leading-5 text-muted">{description}</p>}
    </div>{trailing}
  </div>;
}
