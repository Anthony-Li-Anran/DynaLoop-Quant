import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

type ModalDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
};

export function ModalDialog({
  open,
  title,
  description,
  onClose,
  children,
  className = "",
}: ModalDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;

      const focusable = dialog.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialog}
        aria-labelledby={titleId}
        aria-modal="true"
        className={`relative my-auto w-full max-w-xl overflow-hidden rounded-xl border border-line bg-surface shadow-2xl shadow-black/40 ${className}`}
        tabIndex={-1}
        role="dialog"
      >
        <div className="h-px bg-gradient-to-r from-transparent via-accent/70 to-transparent" />
        <header className="flex items-start justify-between gap-5 border-b border-line/80 px-5 py-5 sm:px-7">
          <div className="min-w-0">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-[0.16em] text-accent/80">
              {t("DynaLoop · Data")}
            </p>
            <h2 id={titleId} className="text-base font-semibold tracking-wide text-ink">
              {title}
            </h2>
            {description && (
              <p className="mt-1.5 max-w-lg text-xs leading-5 text-muted">
                {description}
              </p>
            )}
          </div>
          <button
            ref={closeButton}
            type="button"
            aria-label={t("Close dialog")}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-line bg-elevated/50 text-muted transition-colors hover:border-muted hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            onClick={onClose}
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </header>
        <div className="p-5 sm:p-7">{children}</div>
      </section>
    </div>
  );
}
