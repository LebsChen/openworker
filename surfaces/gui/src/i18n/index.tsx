import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getSettings, setLocale as persistLocale } from "../api";
import en from "./catalogs/en.json";
import zhCN from "./catalogs/zh-CN.json";

export type Locale = "en" | "zh-CN";
type Catalog = Record<string, string>;

const catalogs: Record<Locale, Catalog> = { en, "zh-CN": zhCN };
let activeLocale: Locale = systemLocale();

function translate(locale: Locale, key: string, vars?: Record<string, string | number>): string {
  const fallback = catalogs.en[key] ?? key;
  let value = catalogs[locale][key] ?? fallback;
  for (const [name, replacement] of Object.entries(vars || {})) {
    value = value.split(`{${name}}`).join(String(replacement));
  }
  return value;
}

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => Promise<void>;
  t: typeof t;
};

const I18nContext = createContext<I18nContextValue>({
  locale: "en",
  setLocale: async () => {},
  t,
});

function systemLocale(): Locale {
  return navigator.language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setCurrentLocale] = useState<Locale>(() => systemLocale());

  useEffect(() => {
    getSettings()
      .then((settings) => {
        const stored = settings.locale;
        if (stored === "en" || stored === "zh-CN") {
          activeLocale = stored;
          setCurrentLocale(stored);
        }
      }).catch(() => {});
  }, []);

  const setLocale = async (next: Locale) => {
    activeLocale = next;
    setCurrentLocale(next);
    await persistLocale(next);
  };
  const value = useMemo(() => ({ locale, setLocale, t }), [locale]);
  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}

export function useT(): (key: string, vars?: Record<string, string | number>) => string {
  const { locale } = useI18n();
  return useMemo(() => (key, vars) => translate(locale, key, vars), [locale]);
}

export function t(key: string, vars?: Record<string, string | number>): string {
  return translate(activeLocale, key, vars);
}

export function availableLocales(): { value: Locale; label: string }[] {
  return [
    { value: "en", label: "English" },
    { value: "zh-CN", label: "简体中文" },
  ];
}
