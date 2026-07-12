import {
  buildAuthHeaders,
  buildTaskBody,
  taskUrl,
  webBaseUrl,
  loginStrings,
  shouldClearToken,
  handleExternalMessage,
  TOKEN_KEY,
  EXPIRES_KEY,
  DEFAULT_GATEWAY,
} from "./auth.js";

// 右键菜单项 -> 使用哪个网关 agent。
const MENU_AGENT = {
  "agent-bridge-summary": "summary_page",
  "agent-bridge-jobmatch": "job_match"
};

// 菜单文字跟随语言偏好:zh/en 强制;"browser"/"auto" 按浏览器界面语言。
const MENU_TITLES = {
  zh: {
    "agent-bridge-summary": "Agent Bridge: 总结此页面",
    "agent-bridge-jobmatch": "Agent Bridge: 分析与简历匹配"
  },
  en: {
    "agent-bridge-summary": "Agent Bridge: Summarize this page",
    "agent-bridge-jobmatch": "Agent Bridge: Match against my resume"
  }
};

// 记录每个 tab 本次点击选择的 agent;content.js 回传上下文时再读取。
const pendingAgent = {};
// 右键事件里 Chrome 给的选区快照(info.selectionText)。比 content.js 里
// window.getSelection() 可靠 —— 菜单触发脚本注入时,页面选区常已被清除。
const pendingSelection = {};

function browserLang() {
  const ui = (chrome.i18n.getUILanguage() || "en").toLowerCase();
  return ui.startsWith("zh") ? "zh" : "en";
}

// 错误文案只有 zh/en 两版；"auto"/"browser" 等偏好在这里归一化到界面语言。
function errLang(lang) {
  return lang === "zh" || lang === "en" ? lang : browserLang();
}

// 打开登录页；3 秒内同一地址只开一次，避免倒计时结束和手动点击重复开标签。
let lastLoginOpen = { url: "", at: 0 };
function openLoginTab(url) {
  const now = Date.now();
  if (url === lastLoginOpen.url && now - lastLoginOpen.at < 3000) return;
  lastLoginOpen = { url, at: now };
  chrome.tabs.create({ url });
}

// 面板倒计时结束时发消息回来打开登录页(面板在页面上下文，开不了标签页)。
chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === "AGENT_BRIDGE_OPEN_LOGIN" && message.url) {
    openLoginTab(message.url);
  }
});

function getGatewayConfig() {
  return chrome.storage.local
    .get({ [TOKEN_KEY]: "" })
    .then((cfg) => ({ base: DEFAULT_GATEWAY, token: cfg[TOKEN_KEY] }));
}

async function menuLang() {
  const { langPref } = await chrome.storage.sync.get({ langPref: "browser" });
  return langPref === "zh" || langPref === "en" ? langPref : browserLang();
}

async function syncMenuTitles() {
  const titles = MENU_TITLES[await menuLang()];
  for (const [id, title] of Object.entries(titles)) {
    chrome.contextMenus.update(id, { title });
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(async () => {
    const titles = MENU_TITLES[await menuLang()];
    for (const id of Object.keys(MENU_AGENT)) {
      chrome.contextMenus.create({
        id,
        title: titles[id],
        contexts: ["page", "selection"]
      });
    }
  });
});

// popup 里切换语言后立即更新菜单文字(事件会唤醒 service worker)。
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && changes.langPref) {
    syncMenuTitles();
  }
});

// 浏览器启动时同步一次,覆盖"跟随浏览器"且浏览器界面语言变了的情况。
chrome.runtime.onStartup.addListener(() => {
  syncMenuTitles();
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const agent = MENU_AGENT[info.menuItemId];
  if (!agent || !tab.id) {
    return;
  }
  pendingAgent[tab.id] = agent;
  pendingSelection[tab.id] = info.selectionText || "";

  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["content.js"]
  });
});

// 把弹窗里的语言偏好解析成网关需要的 lang 值:
// "browser"(默认) -> 按浏览器界面语言解析为 zh/en;"zh"/"en"/"auto" 原样透传。
async function resolveLang() {
  const { langPref } = await chrome.storage.sync.get({ langPref: "browser" });
  return langPref === "browser" ? browserLang() : langPref;
}

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.type !== "AGENT_BRIDGE_CONTEXT" || !sender.tab) {
    return;
  }

  const tabId = sender.tab.id;
  const agent = pendingAgent[tabId] || "summary_page";
  delete pendingAgent[tabId];

  // 优先用右键事件的选区快照(可靠);content.js 的 getSelection 仅作兜底。
  const snapshot = pendingSelection[tabId];
  delete pendingSelection[tabId];
  const payload = { ...message.payload };
  if (snapshot && snapshot.trim()) payload.selectedText = snapshot;

  console.log(
    "[Agent Bridge] context received:", agent,
    "selection chars:", (payload.selectedText || "").length,
    "page chars:", (payload.pageText || "").length,
    message.payload && message.payload.url
  );
  showResult(tabId, { state: "loading", source: message.payload && message.payload.url });

  resolveLang().then((lang) =>
    dispatchTask({
      tabId,
      lang,
      agent,
      source: (message.payload && message.payload.url) || "",
      body: () => buildTaskBody(payload, { agent, lang }),
    })
  );
});

// Shared task dispatch: builds the request, handles token/timeout/keep-alive,
// renders the result panel. Used by both the stage-one context flow and the
// on-demand continuation flow. `opts.body()` returns the JSON body object.
function dispatchTask({ tabId, lang, agent, source, body, suppressErrorPanel }) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  const keepAlive = setInterval(
    () => chrome.runtime.getPlatformInfo(() => {}),
    20000
  );
  const done = () => {
    clearTimeout(timeout);
    clearInterval(keepAlive);
  };

  return getGatewayConfig()
    .then(({ base, token }) =>
      fetch(taskUrl(base), {
        method: "POST",
        headers: buildAuthHeaders(token),
        body: JSON.stringify(body()),
        signal: controller.signal,
      }).then((response) => {
        if (shouldClearToken(response.status)) {
          chrome.storage.local.remove([TOKEN_KEY, EXPIRES_KEY]);
          done();
          const loginUrl = webBaseUrl(base);
          const s = loginStrings(errLang(lang));
          // 不立刻开标签页：面板里先跑倒计时，让用户明白将要发生什么，避免以为中招。
          // 倒计时结束(或用户点按钮)后由面板发消息回来打开登录页。
          showResult(tabId, {
            state: "error",
            source,
            errorTitle: s.title,
            errorHint: s.hint,
            loginUrl,
            loginLabel: s.button,
            loginCountdownTpl: s.countdownTpl,
            loginCountdown: 5,
            loginOpened: s.opened,
            text: s.text(loginUrl),
          });
          return null;
        }
        return response.json();
      })
    )
    .then((task) => {
      if (!task) return false; // 401 已处理
      done();
      showResult(tabId, {
        state: "result",
        html: task.result_html,
        sections: task.sections || [],
        actions: task.actions || [],
        agent,
        lang,
        result: task.result || "",
        text: task.result || task.detail || "(no result)",
        source: (task.request && task.request.url) || source,
        durationMs: task.duration_ms,
      });
      return true;
    })
    .catch((error) => {
      done();
      console.error("[Agent Bridge] gateway request failed:", error);
      if (suppressErrorPanel) return false; // caller handles failure inline (keeps stage-1 panel)
      const hint =
        error.name === "AbortError"
          ? "请求超时,网关无响应。"
          : "无法连接网关 (" + error.message + ")。";
      showResult(tabId, {
        state: "error",
        source,
        errorHint: hint,
        errorCmd: "./dev-start backend",
        text: "Agent Bridge 出错:" + hint,
      });
      return false;
    });
}

// On-demand follow-up (e.g. 生成求职信). The panel button sends the stage-1
// raw result back as priorResult; we re-POST /tasks for the named sections and
// re-render the full merged panel. On failure we reply {ok:false} so the page
// re-enables its button and keeps the stage-1 result visible.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "AGENT_BRIDGE_CONTINUE" || !sender.tab) return;
  const tabId = sender.tab.id;

  dispatchTask({
    tabId,
    lang: message.lang,
    agent: message.agent,
    source: message.url || "",
    body: () =>
      buildTaskBody(
        { url: message.url || "" },
        {
          agent: message.agent,
          lang: message.lang,
          sections: message.sections,
          priorResult: message.priorResult,
        }
      ),
    suppressErrorPanel: true,
  }).then((ok) => sendResponse({ ok: !!ok }));

  return true; // async sendResponse
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

  // 区块文字超过该字符数则默认折叠(点击展开)。
  const SECTION_COLLAPSE_CHARS = 160;

  const copyTextTo = (btn, text) => {
    if (!navigator.clipboard || !navigator.clipboard.writeText) return;
    navigator.clipboard
      .writeText(text)
      .then(() => {
        const old = btn.innerHTML;
        btn.innerHTML = ICON_CHECK + "<span>已复制</span>";
        btn.classList.add("copied");
        setTimeout(() => {
          btn.innerHTML = old;
          btn.classList.remove("copied");
        }, 1600);
      })
      .catch(() => {});
  };

  // job_match 的结构化区块:结论(高亮 lede)+ 其余可折叠/可复制区块。
  const renderSections = (container, sections) => {
    sections.forEach((s) => {
      if (s.id === "conclusion") {
        const lede = el("div", "lede");
        lede.innerHTML = s.html; // sanitized server-side
        container.append(lede);
        return;
      }
      const sec = el("details", "sec");
      const summary = el("summary", "sec-head");
      const caret = el("span", "sec-caret");
      caret.textContent = "▸";
      const title = el("span", "sec-title");
      title.textContent = s.title || "";
      summary.append(caret, title);

      const secBody = el("div", "sec-body");
      secBody.innerHTML = s.html; // sanitized server-side
      const textLen = (secBody.textContent || "").trim().length;
      // collapsible=false 的区块(如业务介绍)始终展开;其余超长才默认折叠。
      sec.open = s.collapsible === false || textLen <= SECTION_COLLAPSE_CHARS;

      if (s.copyable) {
        const cbtn = el("button", "sec-copy");
        cbtn.type = "button";
        cbtn.innerHTML = ICON_COPY + "<span>复制</span>";
        cbtn.addEventListener("click", (e) => {
          e.preventDefault(); // 阻止 <details> 折叠切换
          e.stopPropagation();
          copyTextTo(cbtn, (secBody.textContent || "").trim());
        });
        summary.append(cbtn);
      }

      sec.append(summary, secBody);
      container.append(sec);
    });
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

    /* 未悬停时淡出,尽量不挡住页面内容;悬停/键盘聚焦时恢复完整深色面板。
       JS 在渲染后延迟加上 .ab-dim(结果先完整展示几秒),:hover 规则在后,
       同特异性下后者生效。 */
    :host { transition: opacity .3s ease; }
    :host(.ab-dim) { opacity: .28; }
    :host(:hover), :host(:focus-within) { opacity: 1; }

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

    /* job_match: collapsible / copyable sections */
    .lede :first-child { margin-top: 0; }
    .lede :last-child { margin-bottom: 0; }
    .lede p { margin: 0; }
    .sec { border: 1px solid var(--hairline); border-radius: 9px; margin: 10px 0; background: var(--ink-raised); overflow: hidden; }
    .sec > summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 8px; padding: 10px 12px; font-weight: 600; font-size: 13.5px; user-select: none; }
    .sec > summary::-webkit-details-marker { display: none; }
    .sec-caret { color: var(--text-dim); font-size: 10px; transition: transform .15s; }
    .sec[open] .sec-caret { transform: rotate(90deg); }
    .sec-title { flex: 1; min-width: 0; }
    .sec-copy { flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px; background: var(--signal-soft); color: var(--signal); border: none; border-radius: 6px; padding: 4px 9px; font-size: 11px; font-weight: 600; cursor: pointer; }
    .sec-copy:hover { filter: brightness(1.18); }
    .sec-copy svg { width: 13px; height: 13px; }
    .sec-body { padding: 4px 12px 12px; }
    .sec-body > :first-child { margin-top: .2em; }
    .sec-body > :last-child { margin-bottom: 0; }

    .ab-actions { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
    .ab-action { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 12px; background: var(--signal-soft); color: var(--signal); border: 1px solid var(--signal); border-radius: 8px; font-size: 13.5px; font-weight: 600; cursor: pointer; }
    .ab-action:hover { filter: brightness(1.12); }
    .ab-action:disabled { opacity: .6; cursor: default; }
    .ab-action-err { margin-top: 8px; color: var(--alert); font-size: 12.5px; }

    /* error: name what broke and hand over the fix. */
    .error-head { display: flex; align-items: center; gap: 7px; color: var(--alert); font-weight: 600; font-size: 13.5px; margin-bottom: 9px; }
    .error-msg { margin: 0; color: var(--text); }
    .error-sub { margin: 12px 0 7px; color: var(--text-dim); font-size: 12.5px; }
    .login-link { display: inline-flex; align-items: center; gap: 6px; margin-top: 12px; padding: 10px 16px; background: var(--signal); color: var(--ink); border: 1px solid var(--signal); border-radius: 8px; font-size: 13.5px; font-weight: 600; text-decoration: none; }
    .login-link:hover { filter: brightness(1.08); }
    .login-note { margin-top: 10px; font-size: 12.5px; color: var(--text-dim); }
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
      const txt = (payload.text || body.innerText || "")
        .replace(/^@@SECTION\s+\w+\s*$/gm, "")
        .trim();
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
    label.innerHTML = 'Reading and analyzing the information<span class="blink">…</span>';
    const skel = el("div", "skel");
    skel.innerHTML =
      '<span class="sk lede-sk"></span><span class="sk s1"></span>' +
      '<span class="sk s2"></span><span class="sk s3"></span><span class="sk s4"></span>';
    wrap.append(rail, label, skel);
    body.append(wrap);
  } else if (state === "error") {
    const wrap = el("div", "error");
    const eh = el("div", "error-head");
    // 401 给出登录入口时,标题不是"连接失败"而是"需要登录"(文案已按语言本地化)。
    const errTitle =
      payload.errorTitle || (payload.loginUrl ? "需要登录" : "连接失败");
    eh.innerHTML = ICON_ALERT + "<span>" + errTitle + "</span>";
    const msg = el("p", "error-msg");
    msg.textContent = payload.errorHint || payload.text || "发生未知错误。";
    wrap.append(eh, msg);
    if (payload.loginUrl) {
      // 醒目的登录按钮(手动点立即在新标签页打开)。
      const link = el("a", "login-link");
      link.href = payload.loginUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = payload.loginLabel || payload.loginUrl;
      wrap.append(link);

      // 倒计时后自动打开,先告诉用户接下来会发生什么;手动点按钮或关面板则取消。
      if (payload.loginCountdownTpl) {
        const note = el("div", "login-note");
        let remaining = payload.loginCountdown || 5;
        let timer = null;
        const stop = () => {
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
        };
        note.textContent = payload.loginCountdownTpl.replace("{n}", remaining);
        timer = setInterval(() => {
          remaining -= 1;
          if (remaining > 0) {
            note.textContent = payload.loginCountdownTpl.replace("{n}", remaining);
            return;
          }
          stop();
          note.textContent = payload.loginOpened || "";
          chrome.runtime.sendMessage({
            type: "AGENT_BRIDGE_OPEN_LOGIN",
            url: payload.loginUrl,
          });
        }, 1000);
        link.addEventListener("click", stop); // 手动点了就别再自动开一个
        close.addEventListener("click", stop); // 关掉面板即视为取消
        wrap.append(note);
      }
    }
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
  } else if (payload.sections && payload.sections.length) {
    renderSections(body, payload.sections);
    if (payload.actions && payload.actions.length) {
      const actionsWrap = el("div", "ab-actions");
      payload.actions.forEach((action) => {
        const btn = el("button", "ab-action");
        btn.type = "button";
        btn.textContent = action.label;
        const err = el("div", "ab-action-err");
        err.style.display = "none";
        btn.addEventListener("click", () => {
          btn.disabled = true;
          const original = action.label;
          btn.textContent = payload.lang === "en" ? "Generating…" : "生成中…";
          err.style.display = "none";
          chrome.runtime.sendMessage(
            {
              type: "AGENT_BRIDGE_CONTINUE",
              sections: action.sections,
              priorResult: payload.result,
              lang: payload.lang,
              url: payload.source,
              agent: payload.agent,
            },
            (resp) => {
              // 成功时后台已整面板重渲染,这里不必处理;失败时恢复按钮并提示。
              if (!resp || !resp.ok) {
                btn.disabled = false;
                btn.textContent = original;
                err.textContent =
                  payload.lang === "en"
                    ? "Generation failed, please retry."
                    : "生成失败,请重试。";
                err.style.display = "block";
              }
            }
          );
        });
        actionsWrap.append(btn, err);
      });
      body.append(actionsWrap);
    }
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

  // 加载中很快就淡出;结果/错误先完整展示几秒再淡出,确保用户注意到。
  // 若此时鼠标正悬停在面板上,:hover 规则会压过 .ab-dim,保持不透明。
  const dimDelay = state === "loading" ? 800 : 4000;
  setTimeout(() => host.classList.add("ab-dim"), dimDelay);
}

// 网页（externally_connectable.matches 内）推送 token / 探测连接。
chrome.runtime.onMessageExternal.addListener((msg, _sender, sendResponse) => {
  const store = {
    get: (key) => chrome.storage.local.get(key).then((obj) => obj[key]),
    set: (obj) => chrome.storage.local.set(obj)
  };
  handleExternalMessage(msg, { store, now: Date.now() }).then((res) => {
    if (res) sendResponse(res);
  });
  return true; // 异步 sendResponse
});
