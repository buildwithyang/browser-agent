const GATEWAY_URL = "http://127.0.0.1:17321/tasks";

// 右键菜单项 -> 使用哪个网关 agent。
const MENU_AGENT = {
  "agent-bridge-summary": "summary_page",
  "agent-bridge-jobmatch": "job_match"
};

// 记录每个 tab 本次点击选择的 agent;content.js 回传上下文时再读取。
const pendingAgent = {};

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "agent-bridge-summary",
      title: "Agent Bridge: 总结此页面",
      contexts: ["page", "selection"]
    });
    chrome.contextMenus.create({
      id: "agent-bridge-jobmatch",
      title: "Agent Bridge: 分析与简历匹配",
      contexts: ["page", "selection"]
    });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const agent = MENU_AGENT[info.menuItemId];
  if (!agent || !tab.id) {
    return;
  }
  pendingAgent[tab.id] = agent;

  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["content.js"]
  });
});

// 把弹窗里的语言偏好解析成网关需要的 lang 值:
// "browser"(默认) -> 按浏览器界面语言解析为 zh/en;"zh"/"en"/"auto" 原样透传。
async function resolveLang() {
  const { langPref } = await chrome.storage.sync.get({ langPref: "browser" });
  if (langPref === "browser") {
    const ui = (chrome.i18n.getUILanguage() || "en").toLowerCase();
    return ui.startsWith("zh") ? "zh" : "en";
  }
  return langPref;
}

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.type !== "AGENT_BRIDGE_CONTEXT" || !sender.tab) {
    return;
  }

  const tabId = sender.tab.id;
  const agent = pendingAgent[tabId] || "summary_page";
  delete pendingAgent[tabId];
  console.log("[Agent Bridge] context received:", agent, message.payload && message.payload.url);
  showResult(tabId, { state: "loading", source: message.payload && message.payload.url });

  // Abort if the gateway never responds, so the panel can't get stuck forever.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);

  // Chrome kills an MV3 service worker after ~30s of inactivity, and an
  // in-flight fetch does NOT reset that idle timer — agent runs longer than
  // 30s would die silently and leave the panel stuck on "loading". Calling
  // any extension API resets the timer, so poke one every 20s until the
  // request settles.
  const keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(() => {}), 20000);

  resolveLang().then((lang) => {
    console.log("[Agent Bridge] lang:", lang);
    return fetch(GATEWAY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...message.payload, agent, lang }),
      signal: controller.signal
    });
  })
    .then((response) => {
      console.log("[Agent Bridge] gateway responded:", response.status);
      return response.json();
    })
    .then((task) => {
      clearTimeout(timeout);
      clearInterval(keepAlive);
      console.log("[Agent Bridge] task:", task.status, task.duration_ms + "ms");
      showResult(tabId, {
        state: "result",
        html: task.result_html,
        text: task.result || task.detail || "(no result)",
        source: (task.request && task.request.url) || (message.payload && message.payload.url),
        durationMs: task.duration_ms
      });
    })
    .catch((error) => {
      clearTimeout(timeout);
      clearInterval(keepAlive);
      console.error("[Agent Bridge] gateway request failed:", error);
      const hint =
        error.name === "AbortError"
          ? "请求超时,网关无响应。"
          : "无法连接网关 (" + error.message + ")。";
      showResult(tabId, {
        state: "error",
        source: message.payload && message.payload.url,
        errorHint: hint,
        errorCmd: "cd gateway && uv run uvicorn app.main:app --host 127.0.0.1 --port 17321",
        text: "Agent Bridge 出错:" + hint
      });
    });
});

// Render the agent result in an overlay panel injected into the originating page.
// `payload.html` is sanitized server-side (markdown -> safe HTML); `payload.text`
// is a plain-text fallback (used for the placeholder and error messages).
function showResult(tabId, payload) {
  chrome.scripting.executeScript({
    target: { tabId },
    func: renderPanel,
    args: [payload]
  });
}

function renderPanel(payload) {
  const HOST_ID = "agent-bridge-host";
  const old = document.getElementById(HOST_ID);
  if (old) old.remove();

  payload = payload || {};
  // Infer the state for older call shapes that only sent { html } or { text }.
  const state = payload.state || (payload.html ? "result" : "loading");

  const el = (tag, cls) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  };
  // Inline SVGs use currentColor so the surrounding CSS controls their hue —
  // presentation attributes can't read CSS custom properties.
  const MARK =
    '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none">' +
    '<path d="M1.6 11.2C4.6 5.6 11.4 5.6 14.4 11.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
    '<circle cx="1.6" cy="11.2" r="1.7" fill="currentColor"/>' +
    '<circle cx="14.4" cy="11.2" r="1.7" fill="currentColor"/></svg>';
  const ICON_COPY =
    '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="5" width="8.5" height="9.5" rx="1.6"/><path d="M11 3.5H4A1.5 1.5 0 0 0 2.5 5v7.5"/></svg>';
  const ICON_CHECK =
    '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.4l3.3 3.3L13 4.8"/></svg>';
  const ICON_CLOSE =
    '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
  const ICON_ALERT =
    '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M8 2.4L15 14H1z" stroke-linecap="round"/><path d="M8 6.6v3.1" stroke-linecap="round"/><circle cx="8" cy="11.8" r=".55" fill="currentColor" stroke="none"/></svg>';

  // The host lives in the page; !important keeps page CSS from moving it.
  // All visible styling lives inside the Shadow DOM, fully isolated from the page.
  const host = el("div");
  host.id = HOST_ID;
  const hostStyle = {
    position: "fixed",
    top: "16px",
    right: "16px",
    width: "440px",
    "max-width": "92vw",
    "z-index": "2147483647"
  };
  for (const [k, v] of Object.entries(hostStyle)) {
    host.style.setProperty(k, v, "important");
  }

  const shadow = host.attachShadow({ mode: "open" });

  const style = el("style");
  style.textContent = `
    :host { all: initial; }
    * { box-sizing: border-box; }

    .panel {
      /* Cool blue-black instrument chassis; a single warm "signal" accent. */
      --ink: #14161B; --ink-raised: #1B1E26; --ink-sunken: #0E1014;
      --hairline: #2A2E39; --text: #E6E8EE; --text-dim: #969CAB;
      --signal: #F5B544; --signal-soft: rgba(245,181,68,.13); --signal-glow: rgba(245,181,68,.55);
      --link: #8FB6FF; --alert: #E8846B;
      --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace;

      font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
        "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--text); background: var(--ink);
      border: 1px solid var(--hairline); border-radius: 12px;
      box-shadow: 0 18px 50px -12px rgba(0,0,0,.6), 0 1px 0 0 rgba(255,255,255,.03) inset;
      max-height: 74vh; display: flex; flex-direction: column; overflow: hidden;
      animation: ab-rise .3s cubic-bezier(.2,.75,.25,1) both;
    }
    @keyframes ab-rise { from { opacity: 0; transform: translateY(-8px) scale(.98); } to { opacity: 1; transform: none; } }

    .head { padding: 11px 11px 10px 14px; background: linear-gradient(180deg, var(--ink-raised), var(--ink)); border-bottom: 1px solid var(--hairline); }
    .head-row { display: flex; align-items: center; gap: 8px; }
    .brand { display: flex; align-items: center; gap: 7px; flex: 1; min-width: 0; }
    .brand .mark { color: var(--signal); display: flex; }
    .wordmark { font-family: var(--mono); font-size: 11px; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; }
    .actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
    .actions button { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; padding: 0; background: none; border: none; border-radius: 6px; color: var(--text-dim); cursor: pointer; transition: background .15s, color .15s; }
    .actions button:hover { background: var(--signal-soft); color: var(--text); }
    .actions button:focus-visible { outline: 2px solid var(--signal); outline-offset: 1px; }
    .actions .copied { color: var(--signal); }

    .body { padding: 16px 18px 18px; overflow: auto; }

    /* loading: the "bridge scan" — a signal travelling between two endpoints. */
    .rail { position: relative; height: 2px; background: var(--hairline); border-radius: 2px; margin: 6px 3px 16px; }
    .rail::before, .rail::after { content: ""; position: absolute; top: 50%; width: 6px; height: 6px; border-radius: 50%; background: var(--text-dim); transform: translate(-50%, -50%); }
    .rail::before { left: 0; } .rail::after { left: 100%; }
    .pulse { position: absolute; top: 50%; left: 0; width: 7px; height: 7px; margin-left: -3.5px; border-radius: 50%; background: var(--signal); box-shadow: 0 0 9px 1px var(--signal-glow); transform: translateY(-50%); animation: ab-travel 1.6s cubic-bezier(.45,0,.55,1) infinite; }
    @keyframes ab-travel { 0%, 100% { left: 0; } 50% { left: 100%; } }
    .loading-label { font-family: var(--mono); font-size: 11.5px; color: var(--text-dim); letter-spacing: .02em; margin-bottom: 16px; }
    .loading-label .blink { color: var(--signal); animation: ab-blink 1.2s steps(2, jump-none) infinite; }
    @keyframes ab-blink { 50% { opacity: .25; } }
    .sk { display: block; height: 11px; border-radius: 5px; margin: 9px 0; background: linear-gradient(90deg, var(--ink-raised) 25%, #242834 50%, var(--ink-raised) 75%); background-size: 200% 100%; animation: ab-shimmer 1.5s ease infinite; }
    .sk.lede-sk { height: 19px; width: 80%; margin-bottom: 18px; }
    .sk.s1 { width: 96%; } .sk.s2 { width: 76%; } .sk.s3 { width: 90%; } .sk.s4 { width: 60%; }
    @keyframes ab-shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }

    /* result: promote the agent's one-line summary to a lede. */
    .body > :first-child { margin-top: 0; }
    .body > :last-child { margin-bottom: 0; }
    .lede { font-size: 19px; line-height: 1.42; font-weight: 600; color: var(--text); border-left: 3px solid var(--signal); padding-left: 14px; margin: 0 0 18px; }
    .body h1, .body h2, .body h3, .body h4 { margin: 1em 0 .4em; line-height: 1.3; font-weight: 600; }
    .body h1 { font-size: 1.25em; } .body h2 { font-size: 1.12em; } .body h3 { font-size: 1.02em; }
    .body h4 { font-size: .95em; color: var(--text-dim); }
    .body p { margin: .55em 0; }
    .body ul, .body ol { margin: .55em 0; padding-left: 1.3em; }
    .body li { margin: .42em 0; padding-left: 3px; }
    .body li::marker { color: var(--signal); }
    .body a { color: var(--link); text-decoration: none; }
    .body a:hover { text-decoration: underline; }
    .body strong { color: #fff; font-weight: 600; }
    .body code { background: var(--ink-sunken); padding: .12em .38em; border-radius: 4px; font-family: var(--mono); font-size: .88em; color: #D7DBE3; }
    .body pre { background: var(--ink-sunken); padding: 12px; border-radius: 8px; overflow: auto; border: 1px solid var(--hairline); }
    .body pre code { background: none; padding: 0; }
    .body blockquote { margin: .6em 0; padding: .2em .9em; border-left: 2px solid var(--signal); color: var(--text-dim); }
    .body hr { border: none; border-top: 1px solid var(--hairline); margin: 1em 0; }
    .body table { border-collapse: collapse; margin: .6em 0; width: 100%; }
    .body th, .body td { border: 1px solid var(--hairline); padding: 6px 10px; text-align: left; }
    .body th { background: var(--ink-raised); }

    /* error: name what broke and hand over the fix. */
    .error-head { display: flex; align-items: center; gap: 7px; color: var(--alert); font-weight: 600; font-size: 13.5px; margin-bottom: 9px; }
    .error-msg { margin: 0; color: var(--text); }
    .error-sub { margin: 12px 0 7px; color: var(--text-dim); font-size: 12.5px; }
    .cmd { display: flex; align-items: flex-start; gap: 8px; background: var(--ink-sunken); border: 1px solid var(--hairline); border-radius: 8px; padding: 9px 10px; }
    .cmd code { flex: 1; min-width: 0; white-space: pre-wrap; word-break: break-all; line-height: 1.55; font-family: var(--mono); font-size: 11.5px; color: #C9CDD6; }
    .cmd-copy { flex-shrink: 0; margin-top: 1px; background: var(--signal-soft); color: var(--signal); border: none; border-radius: 6px; padding: 5px 9px; font-size: 11px; font-weight: 600; cursor: pointer; }
    .cmd-copy:hover { filter: brightness(1.18); }

    @media (prefers-reduced-motion: reduce) {
      .panel { animation: none; }
      .pulse { animation: none; left: 50%; }
      .sk { animation: none; }
      .loading-label .blink { animation: none; }
    }
  `;

  const panel = el("div", "panel");
  panel.setAttribute("role", "region");
  panel.setAttribute("aria-label", "Agent Bridge");

  // --- header: brand mark + wordmark + actions + metadata strip ---------
  const head = el("div", "head");
  const row = el("div", "head-row");

  const brand = el("div", "brand");
  const mark = el("span", "mark");
  mark.innerHTML = MARK;
  const word = el("span", "wordmark");
  word.textContent = "AGENT BRIDGE";
  brand.append(mark, word);

  const actions = el("div", "actions");
  if (state === "result") {
    const copyBtn = el("button");
    copyBtn.title = "复制摘要";
    copyBtn.setAttribute("aria-label", "复制摘要");
    copyBtn.innerHTML = ICON_COPY;
    copyBtn.addEventListener("click", () => {
      const txt = payload.text || body.innerText || "";
      if (!navigator.clipboard || !navigator.clipboard.writeText) return;
      navigator.clipboard.writeText(txt).then(() => {
        copyBtn.innerHTML = ICON_CHECK;
        copyBtn.classList.add("copied");
        copyBtn.title = "已复制";
        setTimeout(() => {
          copyBtn.innerHTML = ICON_COPY;
          copyBtn.classList.remove("copied");
          copyBtn.title = "复制摘要";
        }, 1600);
      }).catch(() => {});
    });
    actions.append(copyBtn);
  }
  const close = el("button");
  close.title = "关闭";
  close.setAttribute("aria-label", "关闭");
  close.innerHTML = ICON_CLOSE;
  close.addEventListener("click", () => host.remove());
  actions.append(close);

  row.append(brand, actions);
  head.append(row);

  // --- body: one of three states ---------------------------------------
  const body = el("div", "body");
  body.setAttribute("aria-live", "polite");

  if (state === "loading") {
    const wrap = el("div", "loading");
    const rail = el("div", "rail");
    rail.innerHTML = '<span class="pulse"></span>';
    const label = el("div", "loading-label");
    label.innerHTML = '正在阅读页面并生成摘要<span class="blink">…</span>';
    const skel = el("div", "skel");
    skel.innerHTML =
      '<span class="sk lede-sk"></span><span class="sk s1"></span>' +
      '<span class="sk s2"></span><span class="sk s3"></span><span class="sk s4"></span>';
    wrap.append(rail, label, skel);
    body.append(wrap);
  } else if (state === "error") {
    const wrap = el("div", "error");
    const eh = el("div", "error-head");
    eh.innerHTML = ICON_ALERT + "<span>连接失败</span>";
    const msg = el("p", "error-msg");
    msg.textContent = payload.errorHint || payload.text || "发生未知错误。";
    wrap.append(eh, msg);
    if (payload.errorCmd) {
      const sub = el("p", "error-sub");
      sub.textContent = "请确认本地网关正在运行:";
      const cmd = el("div", "cmd");
      const code = el("code");
      code.textContent = payload.errorCmd;
      const cbtn = el("button", "cmd-copy");
      cbtn.textContent = "复制";
      cbtn.addEventListener("click", () => {
        if (!navigator.clipboard || !navigator.clipboard.writeText) return;
        navigator.clipboard.writeText(payload.errorCmd).then(() => {
          cbtn.textContent = "已复制";
          setTimeout(() => (cbtn.textContent = "复制"), 1500);
        }).catch(() => {});
      });
      cmd.append(code, cbtn);
      wrap.append(sub, cmd);
    }
    body.append(wrap);
  } else if (payload.html) {
    body.innerHTML = payload.html; // sanitized by the gateway before it reaches here
    const firstP = body.querySelector("p");
    if (firstP) firstP.classList.add("lede");
  } else {
    body.textContent = payload.text || "(无结果)";
  }

  panel.append(head, body);
  shadow.append(style, panel);
  document.body.appendChild(host);
}
