import { quickInsightView } from "./quick-insight.js";
import { canSend } from "./workspace.js";

export const WORKSPACE_GET = "AGENT_BRIDGE_WORKSPACE_GET";
export const WORKSPACE_SEND = "AGENT_BRIDGE_WORKSPACE_SEND";
export const WORKSPACE_UPDATED = "AGENT_BRIDGE_WORKSPACE_UPDATED";

const COPY = {
  en: {
    workspace: "Shared Workspace",
    noPage: "No active page",
    ready: "Ready",
    loading: "Working",
    offline: "Workspace offline",
    empty: "Open a Quick Insight Action on a page to establish a shared Workspace.",
    noHistory: "No shared history yet. Choose an Action and send the first instruction.",
    quickInsight: "Quick Insight / read-only",
    artifact: "Latest artifact",
    copy: "Copy",
    copied: "Copied",
    next: "Next instruction",
    placeholder: "Ask a question or direct the next artifact revision…",
    hint: "Enter to send · Shift + Enter for a new line",
    send: "Transmit",
    limit: "Message limit reached. Start a new Workspace from Quick Insight.",
    retry: "The request failed. Your input is preserved — retry when ready.",
    user: "You",
    assistant: "Agent",
  },
  zh: {
    workspace: "共享工作台",
    noPage: "没有活动页面",
    ready: "就绪",
    loading: "处理中",
    offline: "工作台未连接",
    empty: "请先在网页的 Quick Insight 中选择一个 Action，建立共享 Workspace。",
    noHistory: "暂无共享历史。选择 Action 并发送第一条指令。",
    quickInsight: "快速洞察 / 只读",
    artifact: "最新产物",
    copy: "复制",
    copied: "已复制",
    next: "下一步指令",
    placeholder: "继续提问，或说明下一轮产物修改要求…",
    hint: "Enter 发送 · Shift + Enter 换行",
    send: "发送",
    limit: "已达到消息上限。请从 Quick Insight 开始新的 Workspace。",
    retry: "请求失败，输入已保留，可稍后重试。",
    user: "你",
    assistant: "Agent",
  },
};

/** Resolve explicit or browser-following language preferences to a supported locale. */
export function resolveUiLang(lang, uiLanguage = "en") {
  if (lang === "zh" || lang === "en") return lang;
  const browserLocale = typeof uiLanguage === "string" ? uiLanguage : "en";
  return browserLocale.toLowerCase().startsWith("zh") ? "zh" : "en";
}

/** Build a DOM-independent rendering model for one complete Workspace state. */
export function workspaceView(state = {}, lang = "browser", uiLanguage = "en") {
  const locale = resolveUiLang(lang, uiLanguage);
  const strings = COPY[locale];
  const actions = Array.isArray(state.actions)
    ? state.actions.filter((action) => action && typeof action.id === "string")
    : [];
  const actionIds = new Set(actions.map((action) => action.id));
  const selectedActionId = actionIds.has(state.selectedActionId)
    ? state.selectedActionId
    : actions[0]?.id || null;
  const histories = Array.isArray(state.histories) ? [...state.histories] : [];
  const sendAllowed = canSend({ histories });
  return {
    lang: locale,
    strings,
    pageTitle: state.pageTitle || strings.workspace,
    resourceUrl: state.resourceUrl || "",
    actions,
    selectedActionId,
    histories,
    document: state.currentDocument || null,
    insight: state.quickInsight
      ? quickInsightView(state.quickInsight, actions)
      : null,
    canSend: sendAllowed,
    limitText: sendAllowed ? "" : strings.limit,
  };
}

/** Send one request to the service worker and surface runtime transport errors. */
function sendRuntime(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      resolve(response);
    });
  });
}

/** Resolve the active browser tab that owns the current Side Panel Workspace. */
async function activeTabId() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0]?.id ?? null;
}

/** Create a text node element without interpreting gateway or page content as markup. */
function textElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text || "";
  return element;
}

/** Return a short display host for the Workspace resource link. */
function sourceLabel(url) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname === "/" ? "" : parsed.pathname}`;
  } catch {
    return url || "";
  }
}

/** Copy artifact text and briefly expose confirmation on the triggering control. */
async function copyArtifact(button, documentState, strings) {
  if (!navigator.clipboard?.writeText) return;
  await navigator.clipboard.writeText(documentState.text || "");
  button.textContent = strings.copied;
  setTimeout(() => {
    button.textContent = strings.copy;
  }, 1400);
}

/** Render the read-only Quick Insight as context outside the message history. */
function renderInsight(container, view) {
  if (!view.insight) return;
  const card = document.createElement("article");
  card.className = "insight-card";
  card.append(textElement("span", "insight-label", view.strings.quickInsight));
  if (Number.isInteger(view.insight.score)) {
    card.append(textElement("strong", "insight-score", String(view.insight.score)));
  }
  card.append(textElement("h2", "", view.insight.title));
  container.append(card);
}

/** Render the single chronological shared history without grouping by Action. */
function renderHistories(container, view) {
  view.histories.forEach((history, index) => {
    const message = document.createElement("article");
    message.className = `message ${history.role === "user" ? "user" : "assistant"}`;
    message.append(textElement("span", "message-index", String(index + 1).padStart(2, "0")));
    const body = document.createElement("div");
    body.className = "message-body";
    body.append(
      textElement(
        "span",
        "message-role",
        history.role === "user" ? view.strings.user : view.strings.assistant
      ),
      textElement("p", "message-content", history.content)
    );
    message.append(body);
    container.append(message);
  });
}

/** Render the latest document as one visually distinct artifact card. */
function renderDocument(container, view) {
  if (!view.document) return;
  const card = document.createElement("article");
  card.className = "artifact-card";
  const header = document.createElement("header");
  header.className = "artifact-head";
  const title = document.createElement("div");
  title.append(
    textElement("span", "artifact-kind", view.document.kind || view.strings.artifact),
    textElement("h2", "", view.document.title || view.strings.artifact)
  );
  const copyButton = textElement("button", "artifact-copy", view.strings.copy);
  copyButton.type = "button";
  copyButton.addEventListener("click", () => {
    copyArtifact(copyButton, view.document, view.strings).catch(() => {});
  });
  header.append(title, copyButton);
  const body = document.createElement("div");
  body.className = "artifact-body";
  if (view.document.html) {
    // Workspace document HTML is sanitized by the gateway before persistence.
    body.innerHTML = view.document.html;
  } else {
    body.textContent = view.document.text || "";
  }
  card.append(header, body);
  container.append(card);
}

/** Render the timeline, including non-history context and latest artifact. */
function renderTimeline(elements, view, connected) {
  elements.timeline.replaceChildren();
  if (!connected) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.append(
      textElement("span", "empty-index", "00"),
      textElement("h2", "", view.strings.offline),
      textElement("p", "", view.strings.empty)
    );
    elements.timeline.append(empty);
    return;
  }
  renderInsight(elements.timeline, view);
  if (view.histories.length) {
    renderHistories(elements.timeline, view);
  } else {
    elements.timeline.append(textElement("p", "timeline-empty-note", view.strings.noHistory));
  }
  renderDocument(elements.timeline, view);
}

/** Render flat Action chips and keep selection independent from shared history. */
function renderActions(elements, model, view) {
  elements.actionChips.replaceChildren();
  view.actions.forEach((action) => {
    const button = textElement("button", "action-chip", action.title || action.id);
    button.type = "button";
    button.setAttribute("aria-pressed", String(action.id === model.selectedActionId));
    button.disabled = model.loading || !view.canSend;
    button.addEventListener("click", () => {
      model.selectedActionId = action.id;
      renderActions(elements, model, { ...view, selectedActionId: action.id });
      updateComposer(elements, model, { ...view, selectedActionId: action.id });
    });
    elements.actionChips.append(button);
  });
}

/** Synchronize composer labels, disabled states, limit text, and retry feedback. */
function updateComposer(elements, model, view) {
  const hasMessage = !!elements.messageInput.value.trim();
  const connected = !!model.state;
  elements.messageInput.disabled = !connected || model.loading || !view.canSend;
  elements.sendButton.disabled =
    !connected
    || model.loading
    || !view.canSend
    || !model.selectedActionId
    || !hasMessage;
  elements.composerLabel.textContent = view.strings.next;
  elements.messageInput.placeholder = view.strings.placeholder;
  elements.composerHint.textContent = view.canSend ? view.strings.hint : view.limitText;
  elements.turnMeter.textContent = `${view.histories.length} / 10`;
  elements.sendLabel.textContent = model.loading ? `${view.strings.loading}…` : view.strings.send;
  elements.composerError.hidden = !model.error;
  elements.composerError.textContent = model.error || "";
}

/** Render every Side Panel region from the latest canonical Workspace state. */
function render(elements, model) {
  const view = workspaceView(model.state || {}, model.lang, model.uiLanguage);
  model.selectedActionId = model.selectedActionId || view.selectedActionId;
  document.documentElement.lang = view.lang;
  elements.title.textContent = view.pageTitle;
  elements.sourceHost.textContent = sourceLabel(view.resourceUrl) || view.strings.noPage;
  elements.sourceLink.href = view.resourceUrl || "#";
  elements.connectionStatus.textContent = model.loading
    ? view.strings.loading
    : model.state
      ? view.strings.ready
      : view.strings.offline;
  elements.connectionStatus.className = `connection-status ${model.loading ? "busy" : model.state ? "ready" : ""}`;
  renderTimeline(elements, view, !!model.state);
  renderActions(elements, model, view);
  updateComposer(elements, model, view);
}

/** Send one Workspace turn while retaining composer input until canonical success. */
async function submitMessage(elements, model) {
  const message = elements.messageInput.value.trim();
  if (!message || !model.tabId || !model.selectedActionId || model.loading) return;
  const requestTabId = model.tabId;
  const requestActionId = model.selectedActionId;
  const view = workspaceView(model.state || {}, model.lang, model.uiLanguage);
  if (!view.canSend) return;

  model.loading = true;
  model.error = "";
  render(elements, model);
  try {
    const response = await sendRuntime({
      type: WORKSPACE_SEND,
      tabId: requestTabId,
      actionId: requestActionId,
      message,
    });
    if (model.tabId !== requestTabId) return;
    if (!response?.ok) {
      throw new Error(response?.error || view.strings.retry);
    }
    model.state = response.state;
    model.lang = response.lang || model.lang;
    model.selectedActionId = response.state?.selectedActionId || model.selectedActionId;
    elements.messageInput.value = "";
  } catch (error) {
    if (model.tabId !== requestTabId) return;
    model.error = error?.message || view.strings.retry;
  } finally {
    if (model.tabId === requestTabId) {
      model.loading = false;
      render(elements, model);
      if (!model.error) elements.timeline.scrollTop = elements.timeline.scrollHeight;
      elements.messageInput.focus();
    }
  }
}

/** Resolve all stable Side Panel elements once during initialization. */
function sidePanelElements() {
  return {
    title: document.getElementById("workspace-title"),
    sourceLink: document.getElementById("source-link"),
    sourceHost: document.getElementById("source-host"),
    connectionStatus: document.getElementById("connection-status"),
    timeline: document.getElementById("timeline"),
    actionChips: document.getElementById("action-chips"),
    composerLabel: document.getElementById("composer-label"),
    messageForm: document.getElementById("message-form"),
    messageInput: document.getElementById("message-input"),
    composerError: document.getElementById("composer-error"),
    composerHint: document.getElementById("composer-hint"),
    turnMeter: document.getElementById("turn-meter"),
    sendButton: document.getElementById("send-button"),
    sendLabel: document.getElementById("send-label"),
  };
}

/** Reload one tab's Workspace while ignoring responses superseded by a newer tab switch. */
async function loadWorkspaceForTab(elements, model, tabId) {
  model.tabId = tabId;
  model.state = null;
  model.selectedActionId = null;
  model.loading = !!tabId;
  model.error = "";
  render(elements, model);
  if (!tabId) return;

  try {
    const response = await sendRuntime({ type: WORKSPACE_GET, tabId });
    if (model.tabId !== tabId) return;
    if (response?.ok) {
      model.state = response.state;
      model.lang = response.lang || "browser";
      model.selectedActionId = response.state?.selectedActionId || null;
    } else if (response?.error) {
      model.error = response.error;
    }
  } catch (error) {
    if (model.tabId !== tabId) return;
    const locale = resolveUiLang(model.lang, model.uiLanguage);
    model.error = error?.message || COPY[locale].retry;
  } finally {
    if (model.tabId === tabId) {
      model.loading = false;
      render(elements, model);
      if (model.state) elements.messageInput.focus();
    }
  }
}

/** Load the active Workspace and install accessible composer interactions. */
async function initSidePanel() {
  const elements = sidePanelElements();
  const model = {
    tabId: await activeTabId(),
    state: null,
    lang: "browser",
    uiLanguage: chrome.i18n.getUILanguage() || "en",
    selectedActionId: null,
    loading: false,
    error: "",
  };
  elements.messageInput.addEventListener("input", () => {
    updateComposer(
      elements,
      model,
      workspaceView(model.state || {}, model.lang, model.uiLanguage)
    );
  });
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      elements.messageForm.requestSubmit();
    }
  });
  elements.messageForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage(elements, model);
  });
  render(elements, model);

  /** Reload and switch the panel after a successful background seed. */
  const onWorkspaceUpdated = (message) => {
    if (message?.type === WORKSPACE_UPDATED && message.tabId) {
      loadWorkspaceForTab(elements, model, message.tabId).catch(() => {});
    }
  };
  /** Follow the active browser tab even when it has no established Workspace. */
  const onTabActivated = ({ tabId }) => {
    loadWorkspaceForTab(elements, model, tabId).catch(() => {});
  };
  /** Release long-lived extension listeners when Chrome destroys this panel document. */
  const cleanup = () => {
    chrome.runtime.onMessage.removeListener(onWorkspaceUpdated);
    chrome.tabs.onActivated.removeListener(onTabActivated);
  };
  chrome.runtime.onMessage.addListener(onWorkspaceUpdated);
  chrome.tabs.onActivated.addListener(onTabActivated);
  window.addEventListener("unload", cleanup, { once: true });

  await loadWorkspaceForTab(elements, model, model.tabId);
}

// Node tests import workspaceView without a DOM or extension runtime.
if (typeof document !== "undefined" && typeof chrome !== "undefined") {
  initSidePanel().catch(() => {});
}
