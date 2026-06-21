import { useCallback, useEffect, useState } from "react";

import { issueExtensionToken } from "./api.js";
import { EXT_STATE, probeThenAutoConnect, connect } from "./extensionConnect.js";

// 扩展 ID 由 manifest 的固定 key 派生，对所有用户一致；自部署无需再设 VITE_EXTENSION_ID。
// 上架 Chrome 商店后若分配了不同 ID，改这里的默认值（或用 VITE_EXTENSION_ID 覆盖）。
const DEFAULT_EXT_ID = "njllhjolgnfainjapjekgimjbipigpja";
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

const LABEL = {
  [EXT_STATE.DETECTING]: "检测中…",
  [EXT_STATE.NOT_INSTALLED]: "未检测到扩展",
  [EXT_STATE.NOT_CONNECTED]: "扩展已安装，未连接",
  [EXT_STATE.CONNECTED]: "已连接",
};

// 把「未连上」拆成可操作的具体原因，避免一句笼统的“连接失败”。
function diagnose() {
  if (!hasRuntime()) {
    return "页面拿不到扩展通道：确认已安装 Agent Bridge 扩展、并在 chrome://extensions 点过「重新加载」；当前页须在 externally_connectable 允许的域名下（云端 / dev 域名，不是 127.0.0.1）。";
  }
  return `扩展已安装但 ID 不匹配：当前扩展 ID 与前端期望的 ${EXT_ID} 不一致（多见于装了未含 manifest key 的旧版扩展，或商店分配了不同 ID）。请安装含固定 key 的版本，或用 VITE_EXTENSION_ID 覆盖。`;
}

export default function ExtensionCard() {
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
    if (res.state === EXT_STATE.NOT_INSTALLED) setError(diagnose());
    else if (res.state === EXT_STATE.NOT_CONNECTED) setError("扩展已检测到，但未确认连接，请点「重新连接」重试。");
  }, []);

  useEffect(() => {
    run();
  }, [run]);

  const onConnect = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await connect(deps);
      setState(res.ok ? EXT_STATE.CONNECTED : EXT_STATE.NOT_CONNECTED);
      if (!res.ok) setError("连接未被扩展确认，请重试。");
    } catch {
      setState(EXT_STATE.NOT_INSTALLED);
      setError(diagnose());
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="uploader-head">
        <div>
          <h2>浏览器扩展</h2>
          <p className="muted">连接后，扩展将以你的身份调用网关、使用你的简历。</p>
        </div>
        {state === EXT_STATE.CONNECTED ? (
          <span className="badge badge-ok">已连接 ✓</span>
        ) : (
          <button className="btn-primary" onClick={onConnect} disabled={busy || state === EXT_STATE.DETECTING}>
            {busy ? "连接中…" : state === EXT_STATE.NOT_CONNECTED ? "连接扩展" : "重新连接"}
          </button>
        )}
      </div>
      <p className="muted">{LABEL[state]}</p>
      {error && <div className="alert alert-error">{error}</div>}
      {state !== EXT_STATE.CONNECTED && state !== EXT_STATE.DETECTING && (
        <p className="muted">
          还没安装？<a href="/download/agent-bridge-extension.zip" download>下载扩展 zip</a>
          ，解压后在 <code>chrome://extensions</code> 开启「开发者模式」→「加载已解压」选择该目录，再回来点「连接扩展」。
        </p>
      )}
    </section>
  );
}
