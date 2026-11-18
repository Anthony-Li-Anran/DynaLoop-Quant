import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zh from "./locales/zh.json";

export const LANGUAGE_STORAGE_KEY = "dynaloop.lang";
export type AppLanguage = "zh" | "en";

export function readStoredLanguage(): AppLanguage {
  try {
    const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (value === "zh" || value === "en") return value;
  } catch {
    // Storage may be unavailable (private mode / test harness); fall back to default.
  }
  return "zh";
}

export function persistLanguage(language: AppLanguage): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Ignore storage failures; in-memory language still applies for this session.
  }
}

const resources = {
  zh: { translation: zh },
  // English uses the source string as the key. With no "en" resource bundle,
  // i18next returns the key itself, so all existing English strings and tests
  // remain valid without a duplicate dictionary.
};

void i18n.use(initReactI18next).init({
  resources,
  lng: readStoredLanguage(),
  fallbackLng: "en",
  supportedLngs: ["zh", "en"],
  nonExplicitSupportedLngs: true,
  interpolation: { escapeValue: false },
  returnNull: false,
  returnEmptyString: false,
  parseMissingKeyHandler: (key) => key,
});

export function setLanguage(language: AppLanguage): void {
  persistLanguage(language);
  void i18n.changeLanguage(language);
}

export function toggleLanguage(): void {
  setLanguage(i18n.language.startsWith("zh") ? "en" : "zh");
}

export default i18n;
