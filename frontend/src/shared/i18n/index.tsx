// Translations of the user interface (admin UI, display client, device app).
// English is the source catalog (en.ts); de.ts and it.ts are typed against it, so a
// missing translation is a compile error. Placeholders: "{name}".
import {
  createContext,
  Fragment,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { de } from "./de";
import { en, type Key } from "./en";
import { it } from "./it";

export type { Key };
export type Lang = "en" | "de" | "it";
export type Vars = Record<string, string | number>;

export const LANGS: { code: Lang; label: string }[] = [
  { code: "en", label: "English" },
  { code: "de", label: "Deutsch" },
  { code: "it", label: "Italiano" },
];

const DICTS: Record<Lang, Record<Key, string>> = { en, de, it };
const STORAGE_KEY = "justai.lang";

function isLang(value: unknown): value is Lang {
  return value === "en" || value === "de" || value === "it";
}

/** Saved choice, else the browser languages, else English. */
export function detectLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (isLang(saved)) return saved;
  } catch {
    // storage unavailable (private mode): fall through
  }
  for (const l of navigator.languages ?? [navigator.language]) {
    const code = l?.slice(0, 2).toLowerCase();
    if (isLang(code)) return code;
  }
  return "en";
}

// Current language for code outside React components (toasts, date formatting).
let current: Lang = detectLang();

export function tg(key: Key, vars?: Vars): string {
  return translate(current, key, vars);
}

const LOCALES: Record<Lang, string> = { en: "en-GB", de: "de-DE", it: "it-IT" };

export function locale(): string {
  return LOCALES[current];
}

export function translate(lang: Lang, key: Key, vars?: Vars): string {
  const text: string = DICTS[lang][key] ?? en[key] ?? key;
  return vars
    ? text.replace(/\{(\w+)\}/g, (m, name: string) =>
        name in vars ? String(vars[name]) : m,
      )
    : text;
}

export type T = (key: Key, vars?: Vars) => string;

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: T;
}

const I18nContext = createContext<I18n>({
  lang: "en",
  setLang: () => undefined,
  t: (key, vars) => translate("en", key, vars),
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);
  const setLang = useCallback((next: Lang) => {
    current = next;
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // not persisted, still switched
    }
  }, []);
  useEffect(() => {
    current = lang;
    document.documentElement.lang = lang;
  }, [lang]);
  const value = useMemo<I18n>(
    () => ({ lang, setLang, t: (key, vars) => translate(lang, key, vars) }),
    [lang, setLang],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  return useContext(I18nContext);
}

export function useT(): T {
  return useContext(I18nContext).t;
}

/** Translation text with elements in it: rich(t("key"), { url: <Code>…</Code> }). */
export function rich(
  text: string,
  parts: Record<string, ReactNode>,
): ReactNode {
  return text.split(/(\{\w+\})/).map((piece, i) => {
    const name = piece.match(/^\{(\w+)\}$/)?.[1];
    return (
      <Fragment key={i}>{name && name in parts ? parts[name] : piece}</Fragment>
    );
  });
}
