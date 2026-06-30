import { useCallback, useEffect, useState } from "react";

import { issueExtensionToken } from "./api.js";
import { EXT_STATE, probeThenAutoConnect, connect } from "./extensionConnect.js";
import { useI18n } from "./i18n.jsx";

// 扩展 ID 由 manifest 的固定 key 派生，对所有用户一致；自部署无需再设 VITE_EXTENSION_ID。
// 此值即 Chrome 商店为本扩展分配的 ID，已与 manifest 的 key 对齐：
// 商店安装版 与 自部署 load-unpacked 版 共用同一 ID（可用 VITE_EXTENSION_ID 覆盖）。
const DEFAULT_EXT_ID = "cmajoaedbjinocbfdkebaedkdbkhbhai";
const EXT_ID = import.meta.env.VITE_EXTENSION_ID || DEFAULT_EXT_ID;

// 页面侧是否拿到了扩展通道（有匹配 externally_connectable 的扩展时才有 chrome.runtime.sendMessage）。
function hasRuntime() {
  return typeof chrome !== "undefined" && !!(chrome.runtime && chrome.runtime.sendMessage);
}

// 包一层 Promise 的 chrome.runtime.sendMessage（仅此处碰真实 chrome API）。
function sendMessage(extId, msg) {
  return new Promise((resolve, reject) => {
    if (!extId) {
      reject(new Error("no-ext-id"));
      return;
    }
    if (!hasRuntime()) {
      reject(new Error("no-runtime"));
      return;
    }
    try {
      chrome.runtime.sendMessage(extId, msg, (res) => {
        const err = chrome.runtime.lastError;
        if (err) reject(new Error(err.message));
        else resolve(res);
      });
    } catch (e) {
      reject(e);
    }
  });
}

const LABEL_KEY = {
  [EXT_STATE.DETECTING]: "ext.stateDetecting",
  [EXT_STATE.NOT_INSTALLED]: "ext.stateNotInstalled",
  [EXT_STATE.NOT_CONNECTED]: "ext.stateNotConnected",
  [EXT_STATE.CONNECTED]: "ext.stateConnected",
};

// 把「未连上」拆成可操作的具体原因，避免一句笼统的“连接失败”。
function diagnose(t) {
  if (!hasRuntime()) {
    return t("ext.diagnoseNoRuntime");
  }
  return t("ext.diagnoseIdMismatch", { extId: EXT_ID });
}

export default function ExtensionCard() {
  const { t } = useI18n();
  const [state, setState] = useState(EXT_STATE.DETECTING);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const deps = { sendMessage, extId: EXT_ID, issueToken: issueExtensionToken };

  const run = useCallback(async () => {
    setError("");
    // 诊断信息留在控制台，便于排查（不打印 token）。
    console.debug("[ExtensionCard] extId set:", !!EXT_ID, "runtime:", hasRuntime());
    const res = await probeThenAutoConnect(deps);
    setState(res.state);
    if (res.state === EXT_STATE.NOT_INSTALLED) setError(diagnose(t));
    else if (res.state === EXT_STATE.NOT_CONNECTED) setError(t("ext.errNotConnectedConfirm"));
  }, [t]);

  useEffect(() => {
    run();
  }, [run]);

  const onConnect = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await connect(deps);
      setState(res.ok ? EXT_STATE.CONNECTED : EXT_STATE.NOT_CONNECTED);
      if (!res.ok) setError(t("ext.errConnectNotConfirmed"));
    } catch {
      setState(EXT_STATE.NOT_INSTALLED);
      setError(diagnose(t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="uploader-head">
        <div>
          <h2>{t("ext.title")}</h2>
          <p className="muted">{t("ext.desc")}</p>
        </div>
        {state === EXT_STATE.CONNECTED ? (
          <span className="badge badge-ok">{t("ext.connectedBadge")}</span>
        ) : (
          <button className="btn-primary" onClick={onConnect} disabled={busy || state === EXT_STATE.DETECTING}>
            {busy ? t("ext.btnConnecting") : state === EXT_STATE.NOT_CONNECTED ? t("ext.btnConnect") : t("ext.btnReconnect")}
          </button>
        )}
      </div>
      <p className="muted">{t(LABEL_KEY[state] || LABEL_KEY[EXT_STATE.DETECTING])}</p>
      {error && <div className="alert alert-error">{error}</div>}
      {state !== EXT_STATE.CONNECTED && state !== EXT_STATE.DETECTING && (
        <p className="muted">
          {t("ext.installQuestion")}
          <a href="/download/agent-bridge-extension.zip" download>{t("ext.installDownload")}</a>
          {t("ext.installStepsBefore")}<code>chrome://extensions</code>{t("ext.installStepsAfter")}
        </p>
      )}
    </section>
  );
}
