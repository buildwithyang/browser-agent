import { useCallback, useEffect, useState } from "react";

import { issueExtensionToken } from "./api.js";
import { EXT_STATE, probeThenAutoConnect, connect } from "./extensionConnect.js";

const EXT_ID = import.meta.env.VITE_EXTENSION_ID || "";

// 包一层 Promise 的 chrome.runtime.sendMessage（仅此处碰真实 chrome API）。
function sendMessage(extId, msg) {
  return new Promise((resolve, reject) => {
    const runtime = typeof chrome !== "undefined" && chrome.runtime;
    if (!runtime || !runtime.sendMessage || !extId) {
      reject(new Error("no-extension"));
      return;
    }
    try {
      runtime.sendMessage(extId, msg, (res) => {
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

export default function ExtensionCard() {
  const [state, setState] = useState(EXT_STATE.DETECTING);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const deps = { sendMessage, extId: EXT_ID, issueToken: issueExtensionToken };

  const autoConnect = useCallback(async () => {
    setError("");
    const res = await probeThenAutoConnect(deps);
    setState(res.state);
  }, []);

  useEffect(() => {
    autoConnect();
  }, [autoConnect]);

  const onConnect = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await connect(deps);
      setState(res.ok ? EXT_STATE.CONNECTED : EXT_STATE.NOT_CONNECTED);
      if (!res.ok) setError("连接未被扩展确认，请重试。");
    } catch {
      setError("连接失败：请确认已安装扩展，且当前页面在扩展允许的域名下。");
      setState(EXT_STATE.NOT_INSTALLED);
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
      {state === EXT_STATE.NOT_INSTALLED && (
        <p className="muted">未检测到扩展。请先安装 Agent Bridge 扩展并刷新本页。</p>
      )}
      {error && <div className="alert alert-error">{error}</div>}
    </section>
  );
}
