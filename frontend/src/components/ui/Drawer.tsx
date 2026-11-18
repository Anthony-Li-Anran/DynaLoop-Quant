import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

type DrawerProps = {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  width?: "md" | "lg";
};

/** Side drawer: keeps long detail / advanced settings off the main page. */
export function Drawer({
  open,
  title,
  description,
  onClose,
  children,
  width = "md",
}: DrawerProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`flex h-full w-full flex-col border-l border-line bg-surface shadow-2xl shadow-black/40 ${
          width === "lg" ? "max-w-2xl" : "max-w-md"
        }`}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-[0.16em] text-accent/80">
              {t("DynaLoop · Backtests")}
            </p>
            <h2 id={titleId} className="text-base font-semibold text-ink">
              {title}
            </h2>
            {description && (
              <p className="mt-1 text-xs leading-5 text-muted">{description}</p>
            )}
          </div>
          <button
            ref={closeButton}
            type="button"
            aria-label={t("Close drawer")}
            onClick={onClose}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-line bg-elevated/50 text-muted transition-colors hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>
      </aside>
    </div>
  );
}
