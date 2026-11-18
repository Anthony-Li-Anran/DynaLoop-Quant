import { AlertCircle, Inbox, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

type StateProps = {
  title: string;
  description?: string;
  action?: ReactNode;
};

export function LoadingState({ title }: { title?: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-3 rounded-panel border border-line bg-surface px-5 py-6 text-sm text-muted">
      <LoaderCircle aria-hidden className="h-4 w-4 animate-spin text-accent" />
      {title ?? t("Loading data…")}
    </div>
  );
}

export function EmptyState({ title, description, action }: StateProps) {
  return (
    <div className="flex min-h-36 flex-col items-center justify-center rounded-panel border border-dashed border-line bg-surface/50 px-6 py-8 text-center">
      <Inbox aria-hidden className="mb-3 h-5 w-5 text-muted" />
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="mt-1 max-w-md text-xs leading-5 text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ title, description, action }: StateProps) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-panel border border-rose-500/25 bg-rose-500/5 p-5">
      <AlertCircle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" />
      <div>
        <p className="text-sm font-medium text-rose-200">{title}</p>
        {description && <p className="mt-1 break-words text-xs leading-5 text-rose-200/70">{description}</p>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

export function QueryState<T>({
  query,
  children,
  emptyTitle,
}: {
  query: {
    isLoading: boolean;
    error: Error | null;
    data: T | undefined;
  };
  children: (data: T) => ReactNode;
  emptyTitle?: string;
}) {
  const { t } = useTranslation();
  if (query.isLoading) return <LoadingState />;
  if (query.error) {
    return <ErrorState title={t("Unable to load data")} description={query.error.message} />;
  }
  if (query.data === undefined || query.data === null) {
    return <EmptyState title={emptyTitle ?? "No data available"} />;
  }
  return <>{children(query.data)}</>;
}
