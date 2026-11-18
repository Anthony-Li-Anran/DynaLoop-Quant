import { useTranslation } from "react-i18next";
import { setLanguage } from "../../i18n";

export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const isChinese = i18n.language.startsWith("zh");
  return (
    <div className="flex items-center gap-1" role="group" aria-label={t("Language")}>
      <button
        type="button"
        onClick={() => setLanguage("zh")}
        aria-pressed={isChinese}
        className={`rounded px-2 py-1 text-[11px] transition-colors ${isChinese ? "bg-elevated font-semibold text-ink" : "text-muted hover:text-ink"}`}
      >
        {t("Chinese")}
      </button>
      <button
        type="button"
        onClick={() => setLanguage("en")}
        aria-pressed={!isChinese}
        className={`rounded px-2 py-1 text-[11px] transition-colors ${!isChinese ? "bg-elevated font-semibold text-ink" : "text-muted hover:text-ink"}`}
      >
        {t("English")}
      </button>
    </div>
  );
}
