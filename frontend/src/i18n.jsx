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
const SUPPORTED = ["zh", "en"];

// 首选语言:已保存的选择优先,否则按浏览器语言猜(zh* -> 中文,其余 -> 英文)。
function detectLang() {
  if (typeof window === "undefined") return "zh";
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && SUPPORTED.includes(saved)) return saved;
  } catch {
    /* localStorage 不可用时忽略 */
  }
  const nav = (navigator.language || navigator.userLanguage || "").toLowerCase();
  return nav.startsWith("zh") ? "zh" : "en";
}

// 按点号路径取值:resolve(obj, "a.b.c")。
function resolve(obj, path) {
  return path.split(".").reduce((acc, key) => (acc == null ? acc : acc[key]), obj);
}

const LanguageContext = createContext(null);

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(detectLang);

  useEffect(() => {
    if (typeof document !== "undefined") document.documentElement.lang = lang;
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

  // t("区块.键", vars?) -> 当前语言文案;缺失回退中文,再缺失回显 key。
  const t = useCallback(
    (key, vars) => {
      let val = resolve(messages[lang], key);
      if (val === undefined) val = resolve(messages.zh, key);
      if (val === undefined) return key;
      if (typeof val === "string" && vars) {
        return val.replace(/\{(\w+)\}/g, (m, name) =>
          vars[name] != null ? String(vars[name]) : m
        );
      }
      return val;
    },
    [lang]
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return (
    <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useI18n 必须在 <LanguageProvider> 内使用");
  return ctx;
}

// 中 / EN 切换按钮:显示目标语言,点一下切过去。
export function LanguageToggle({ className = "" }) {
  const { lang, setLang } = useI18n();
  const next = lang === "zh" ? "en" : "zh";
  const label = lang === "zh" ? "EN" : "中";
  return (
    <button
      type="button"
      className={`lang-toggle ${className}`.trim()}
      onClick={() => setLang(next)}
      aria-label={lang === "zh" ? "Switch to English" : "切换到中文"}
    >
      {label}
    </button>
  );
}
