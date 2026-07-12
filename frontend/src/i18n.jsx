import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { messages } from "./strings.js";

const STORAGE_KEY = "ab_lang";
export const LANGUAGES = {
  zh: { label: "中文", htmlLang: "zh-CN", locale: "zh-CN" },
  en: { label: "English", htmlLang: "en", locale: "en-US" },
  fr: { label: "Français", htmlLang: "fr", locale: "fr-FR" },
};
const SUPPORTED = Object.keys(LANGUAGES);

function languageCode(value) {
  const code = String(value || "").toLowerCase().split("-")[0];
  return SUPPORTED.includes(code) ? code : null;
}

// 首选语言:已保存的选择优先,再匹配浏览器语言列表,无法匹配时回退英文。
export function detectLang(storage, browserLanguages = []) {
  try {
    const saved = storage?.getItem(STORAGE_KEY);
    if (saved && SUPPORTED.includes(saved)) return saved;
  } catch {
    /* localStorage 不可用时忽略 */
  }
  for (const browserLang of browserLanguages) {
    const matched = languageCode(browserLang);
    if (matched) return matched;
  }
  return "en";
}

function detectBrowserLang() {
  if (typeof window === "undefined") return "en";
  const browserLanguages = navigator.languages?.length
    ? navigator.languages
    : [navigator.language || navigator.userLanguage];
  return detectLang(window.localStorage, browserLanguages);
}

// 按点号路径取值:resolve(obj, "a.b.c")。
function resolve(obj, path) {
  return path.split(".").reduce((acc, key) => (acc == null ? acc : acc[key]), obj);
}

export function resolveMessage(lang, key, catalogs = messages) {
  const fallbackOrder = lang === "fr" ? ["fr", "en", "zh"] : [lang, "zh", "en"];
  for (const candidate of fallbackOrder) {
    const value = resolve(catalogs[candidate], key);
    if (value !== undefined) return value;
  }
  return key;
}

export const LanguageContext = createContext(null);

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(detectBrowserLang);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = LANGUAGES[lang].htmlLang;
    }
  }, [lang]);

  const setLang = useCallback((next) => {
    if (!SUPPORTED.includes(next)) return;
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* 忽略持久化失败 */
    }
  }, []);

  // t("区块.键", vars?) -> 当前语言文案;法语缺失时先回退英文。
  const t = useCallback(
    (key, vars) => {
      const val = resolveMessage(lang, key);
      if (typeof val === "string" && vars) {
        return val.replace(/\{(\w+)\}/g, (m, name) =>
          vars[name] != null ? String(vars[name]) : m
        );
      }
      return val;
    },
    [lang]
  );

  const value = useMemo(
    () => ({ lang, locale: LANGUAGES[lang].locale, setLang, t }),
    [lang, setLang, t]
  );
  return (
    <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useI18n 必须在 <LanguageProvider> 内使用");
  return ctx;
}

// 三语原生选择器:保留键盘、屏幕阅读器和移动端原生交互。
export function LanguageToggle({ className = "" }) {
  const { lang, setLang, t } = useI18n();
  return (
    <select
      className={`lang-toggle lang-select ${className}`.trim()}
      value={lang}
      onChange={(event) => setLang(event.target.value)}
      aria-label={t("nav.language")}
    >
      {Object.entries(LANGUAGES).map(([code, meta]) => (
        <option key={code} value={code}>{meta.label}</option>
      ))}
    </select>
  );
}
