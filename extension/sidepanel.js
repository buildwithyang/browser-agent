import { renderMarkdown } from "./markdown.js";
import { canSendUserMessage } from "./workspace.js";

export const WORKSPACE_GET = "AGENT_BRIDGE_WORKSPACE_GET";
export const WORKSPACE_SEND = "AGENT_BRIDGE_WORKSPACE_SEND";
export const WORKSPACE_UPDATED = "AGENT_BRIDGE_WORKSPACE_UPDATED";
export const WORKSPACE_RESET = "AGENT_BRIDGE_WORKSPACE_RESET";

const COPY = {
  en: {
    workspace: "Shared Workspace",
    noPage: "No active page",
    offline: "Open a Quick Insight Action on a page to start this conversation.",
    noHistory: "No messages yet. Choose an Action and send the first instruction.",
    loading: "Working",
    next: "Next instruction",
    placeholder: "Ask a question or direct the next revision…",
    hint: "Enter to send · Shift + Enter for a new line",
    send: "Send",
    limit: "Message limit reached. Start a new Workspace from Quick Insight.",
    retryFallback: "The request failed. Your input is preserved.",
    retry: "Retry",
    attachment: "Attachment",
    coverLetter: "Cover Letter",
    cv: "CV",
    copy: "Copy Markdown",
    copied: "Copied",
    openCv: "Open CV",
    updateMessage: "Update Agent Bridge to continue.",
    updateGateway: "If this still appears after updating, check the Gateway deployment.",
    updateLink: "Open Chrome Web Store",
  },
  zh: {
    workspace: "共享对话",
    noPage: "没有活动页面",
    offline: "请先在网页的 Quick Insight 中选择一个 Action，开始对话。",
    noHistory: "暂无消息。选择 Action 并发送第一条指令。",
    loading: "处理中",
    next: "下一步指令",
    placeholder: "继续提问，或说明下一轮修改要求…",
    hint: "Enter 发送 · Shift + Enter 换行",
    send: "发送",
    limit: "已达到消息上限。请从 Quick Insight 开始新的 Workspace。",
    retryFallback: "请求失败，输入已保留。",
    retry: "重试",
    attachment: "附件",
    coverLetter: "求职信",
    cv: "简历",
    copy: "复制 Markdown",
    copied: "已复制",
    openCv: "打开简历",
    updateMessage: "请更新 Agent Bridge 后继续。",
    updateGateway: "更新后仍出现此提示，请检查 Gateway 部署。",
    updateLink: "打开 Chrome 应用商店",
  },
};

/** Resolve explicit or browser-following language preferences to a supported locale. */
export function resolveUiLang(lang, uiLanguage = "en") {
  if (lang === "zh" || lang === "en") return lang;
  const browserLocale = typeof uiLanguage === "string" ? uiLanguage : "en";
  return browserLocale.toLowerCase().startsWith("zh") ? "zh" : "en";
}

/** Resolve a Workspace lifecycle event to the tab that the panel should reload. */
export function workspaceLifecycleTarget(message, currentTabId) {
  if (message?.type === WORKSPACE_UPDATED && message.tabId) return message.tabId;
  if (
    message?.type === WORKSPACE_RESET
    && (!message.tabId || message.tabId === currentTabId)
  ) {
    return currentTabId;
  }
  return null;
}

/** Return the optional integer match score from the compact Quick Insight header data. */
function matchScore(quickInsight) {
  const cards = Array.isArray(quickInsight?.cards) ? quickInsight.cards : [];
  const scoreCard = cards.find((card) => card?.type === "score");
  return Number.isInteger(scoreCard?.score) ? scoreCard.score : null;
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
  const sendAllowed = canSendUserMessage(state);
  return {
    lang: locale,
    strings,
    pageTitle: state.pageTitle || strings.workspace,
    resourceUrl: state.resourceUrl || "",
    matchScore: matchScore(state.quickInsight),
    actions,
    selectedActionId,
    histories,
    canSend: sendAllowed,
    limitText: sendAllowed ? "" : strings.limit,
  };
}

/** Convert one failed runtime response into a stable composer-error presentation. */
export function workspaceResponseError(response, fallback = COPY.en.retryFallback) {
  if (response?.type === "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED") {
    return {
      kind: "update-required",
      updateUrl: typeof response.updateUrl === "string" ? response.updateUrl : "",
      requiredVersion: response.requiredVersion ?? null,
    };
  }
  return {
    kind: "retryable",
    message: typeof response?.error === "string" && response.error
      ? response.error
      : fallback,
  };
}

/** Return whether one keyboard event should submit instead of inserting a newline. */
export function shouldSubmitMessage(event) {
  return event?.key === "Enter" && !event.shiftKey && !event.isComposing;
}

/** Format one canonical UTC message timestamp for compact and full local display. */
export function messageTimePresentation(createdAt, lang = "en") {
  const date = new Date(createdAt);
  if (!Number.isFinite(date.getTime())) {
    return { visible: "", title: "", datetime: createdAt || "" };
  }
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  return {
    visible: new Intl.DateTimeFormat(locale, {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date),
    title: new Intl.DateTimeFormat(locale, {
      dateStyle: "full",
      timeStyle: "medium",
    }).format(date),
    datetime: createdAt,
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

/** Create one element whose content is always treated as plain text. */
function textElement(documentRef, tagName, className, text) {
  const element = documentRef.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text || "";
  return element;
}

/** Return a short display host and path for the Workspace resource link. */
function sourceLabel(url) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname === "/" ? "" : parsed.pathname}`;
  } catch {
    return url || "";
  }
}

/** Return one absolute HTTP(S) URL or null for an unsafe/invalid destination. */
function safeHttpUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/** Apply safe new-tab behavior to one link without inventing a fallback URL. */
function configureNewTabLink(link, url) {
  const safeUrl = safeHttpUrl(url);
  if (!safeUrl) {
    link.removeAttribute("href");
    return false;
  }
  link.href = safeUrl;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return true;
}

/** Render sanitized Markdown and harden every retained HTTP(S) link for a new tab. */
function renderMarkdownInto(container, markdown, windowRef) {
  container.innerHTML = renderMarkdown(markdown, windowRef);
  container.querySelectorAll("a").forEach((link) => {
    const href = link.getAttribute("href");
    if (href) configureNewTabLink(link, href);
  });
}

/** Copy raw source text through an injected test seam or the browser Clipboard API. */
async function copyTextValue(text, dependencies = {}) {
  if (typeof dependencies.copyText === "function") {
    await dependencies.copyText(text);
    return;
  }
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
  }
}

/** Render one immutable Attachment inside its originating Assistant message. */
function renderAttachment(documentRef, attachment, view, dependencies) {
  const isCv = attachment?.type === "cv";
  const card = documentRef.createElement("section");
  card.className = `attachment ${isCv ? "cv" : "cover-letter"}`;
  card.setAttribute("aria-label", attachment?.title || view.strings.attachment);

  const header = documentRef.createElement("header");
  header.className = "attachment-header";
  const title = documentRef.createElement("div");
  title.className = "attachment-title";
  title.append(
    textElement(documentRef, "span", "attachment-kicker", view.strings.attachment),
    textElement(
      documentRef,
      "h2",
      "",
      attachment?.title || (isCv ? view.strings.cv : view.strings.coverLetter)
    )
  );
  header.append(title);

  if (isCv) {
    const openLink = textElement(documentRef, "a", "attachment-open", view.strings.openCv);
    configureNewTabLink(openLink, attachment.content);
    openLink.setAttribute("aria-label", `${view.strings.openCv}: ${attachment.title}`);
    header.append(openLink);
  } else {
    const copyButton = textElement(documentRef, "button", "attachment-copy", view.strings.copy);
    copyButton.type = "button";
    copyButton.setAttribute("aria-label", `${view.strings.copy}: ${attachment.title}`);
    copyButton.addEventListener("click", async () => {
      copyButton.disabled = true;
      try {
        await copyTextValue(attachment.content, dependencies);
        copyButton.textContent = view.strings.copied;
      } catch {
        copyButton.textContent = view.strings.copy;
      } finally {
        documentRef.defaultView.setTimeout(() => {
          copyButton.disabled = false;
          copyButton.textContent = view.strings.copy;
        }, 1400);
      }
    });
    header.append(copyButton);
  }
  card.append(header);

  if (!isCv) {
    const body = documentRef.createElement("div");
    body.className = "attachment-body markdown-content";
    renderMarkdownInto(body, attachment.content || "", documentRef.defaultView);
    card.append(body);
  }
  return card;
}

/** Render one role-aware HistoryMessage with timestamp and inline Attachments. */
function renderHistoryMessage(documentRef, history, view, dependencies) {
  const role = history?.role === "user" ? "user" : "assistant";
  const message = documentRef.createElement("article");
  message.className = `message ${role}`;
  const body = documentRef.createElement("div");
  body.className = "message-body";
  const surface = documentRef.createElement("div");
  surface.className = "message-surface";
  const content = documentRef.createElement("div");
  content.className = `message-content${role === "assistant" ? " markdown-content" : ""}`;

  if (role === "user") {
    content.textContent = history.content || "";
  } else {
    renderMarkdownInto(content, history.content || "", documentRef.defaultView);
  }
  surface.append(content);
  if (role === "assistant") {
    for (const item of Array.isArray(history.attachments) ? history.attachments : []) {
      surface.append(renderAttachment(documentRef, item, view, dependencies));
    }
  }

  const timeView = messageTimePresentation(history.created_at, view.lang);
  const meta = documentRef.createElement("div");
  meta.className = "message-meta";
  const time = textElement(documentRef, "time", "", timeView.visible);
  time.dateTime = timeView.datetime;
  time.title = timeView.title;
  meta.append(time);
  body.append(surface, meta);
  message.append(body);
  return message;
}

/** Render the canonical chronological history as the timeline's only content source. */
function renderTimeline(elements, model, view, dependencies) {
  elements.timeline.replaceChildren();
  elements.timeline.setAttribute("aria-busy", String(!!model.loading));
  if (!model.state) {
    elements.timeline.append(
      textElement(elements.documentRef, "p", "timeline-empty-note", view.strings.offline)
    );
    return;
  }
  if (!view.histories.length) {
    elements.timeline.append(
      textElement(elements.documentRef, "p", "timeline-empty-note", view.strings.noHistory)
    );
    return;
  }
  for (const history of view.histories) {
    elements.timeline.append(
      renderHistoryMessage(elements.documentRef, history, view, dependencies)
    );
  }
}

/** Render compact page identity metadata without exposing Workspace lifecycle chrome. */
function renderHeader(elements, view) {
  elements.title.textContent = view.pageTitle;
  elements.sourceHost.textContent = sourceLabel(view.resourceUrl) || view.strings.noPage;
  if (!configureNewTabLink(elements.sourceLink, view.resourceUrl)) {
    elements.sourceLink.removeAttribute("target");
    elements.sourceLink.removeAttribute("rel");
  }
  const hasScore = Number.isInteger(view.matchScore);
  elements.matchScore.hidden = !hasScore;
  elements.matchScore.textContent = hasScore ? `${view.matchScore} / 100` : "";
}

/** Return whether the current composer error requires an Extension update. */
function isUpdateRequired(error) {
  return error?.kind === "update-required"
    || error?.type === "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED";
}

/** Render backend-declared Action chips while keeping shared history untouched. */
function renderActions(elements, model, view) {
  elements.actionChips.replaceChildren();
  const actionsDisabled = model.loading || !view.canSend || isUpdateRequired(model.error);
  view.actions.forEach((action) => {
    const button = textElement(
      elements.documentRef,
      "button",
      "action-chip",
      action.title || action.id
    );
    button.type = "button";
    button.dataset.actionId = action.id;
    button.setAttribute("aria-pressed", String(action.id === model.selectedActionId));
    button.disabled = actionsDisabled;
    button.addEventListener("click", () => {
      model.selectedActionId = action.id;
      elements.actionChips.querySelectorAll(".action-chip").forEach((chip) => {
        chip.setAttribute("aria-pressed", String(chip.dataset.actionId === action.id));
      });
      updateComposer(elements, model, view);
    });
    elements.actionChips.append(button);
  });
}

/** Normalize legacy string errors before rendering the structured composer state. */
function normalizedComposerError(error, strings) {
  if (!error) return null;
  if (typeof error === "string") {
    return workspaceResponseError({ error }, strings.retryFallback);
  }
  if (error.kind) return error;
  return workspaceResponseError(error, strings.retryFallback);
}

/** Render one update-required or ordinary retryable error near the composer. */
function renderComposerError(elements, model, view) {
  const error = normalizedComposerError(model.error, view.strings);
  elements.composerError.replaceChildren();
  elements.composerError.hidden = !error;
  if (!error) return;

  if (error.kind === "update-required") {
    const message = textElement(
      elements.documentRef,
      "div",
      "error-message",
      `${view.strings.updateMessage} ${view.strings.updateGateway}`
    );
    elements.composerError.append(message);
    const link = textElement(
      elements.documentRef,
      "a",
      "error-update-link",
      view.strings.updateLink
    );
    if (configureNewTabLink(link, error.updateUrl)) {
      elements.composerError.append(" ", link);
    }
    return;
  }

  elements.composerError.append(
    textElement(elements.documentRef, "div", "error-message", error.message)
  );
  const retry = textElement(elements.documentRef, "button", "error-retry", view.strings.retry);
  retry.type = "button";
  retry.addEventListener("click", () => {
    if (typeof model.retry === "function") model.retry();
  });
  elements.composerError.append(retry);
}

/** Synchronize composer labels, disabled states, limits, and error feedback. */
function updateComposer(elements, model, view) {
  const hasMessage = !!elements.messageInput.value.trim();
  const connected = !!model.state;
  const updateRequired = isUpdateRequired(normalizedComposerError(model.error, view.strings));
  let hint = view.strings.hint;
  if (!connected) hint = view.strings.offline;
  else if (model.loading) hint = `${view.strings.loading}…`;
  else if (!view.canSend) hint = view.limitText;
  elements.messageInput.disabled = !connected || model.loading || !view.canSend || updateRequired;
  elements.sendButton.disabled =
    !connected
    || model.loading
    || !view.canSend
    || updateRequired
    || !model.selectedActionId
    || !hasMessage;
  elements.composerLabel.textContent = view.strings.next;
  elements.messageInput.placeholder = view.strings.placeholder;
  elements.composerHint.textContent = hint;
  elements.turnMeter.textContent = `${view.histories.length} / 10`;
  elements.sendLabel.textContent = model.loading ? `${view.strings.loading}…` : view.strings.send;
  renderComposerError(elements, model, view);
}

/** Render every Side Panel region from the latest canonical Workspace state. */
function render(elements, model, dependencies = {}) {
  const view = workspaceView(model.state || {}, model.lang, model.uiLanguage);
  const actionIds = new Set(view.actions.map((action) => action.id));
  if (!actionIds.has(model.selectedActionId)) model.selectedActionId = view.selectedActionId;
  elements.documentRef.documentElement.lang = view.lang;
  renderHeader(elements, view);
  renderTimeline(elements, model, view, dependencies);
  renderActions(elements, model, view);
  updateComposer(elements, model, view);

  const priorCount = Number.isInteger(model.renderedHistoryCount)
    ? model.renderedHistoryCount
    : -1;
  if (view.histories.length > priorCount) {
    elements.timeline.scrollTop = elements.timeline.scrollHeight;
  }
  model.renderedHistoryCount = view.histories.length;
  return elements;
}

/** Resolve all stable Side Panel elements from one document. */
function sidePanelElements(documentRef) {
  return {
    documentRef,
    title: documentRef.getElementById("workspace-title"),
    matchScore: documentRef.getElementById("match-score"),
    sourceLink: documentRef.getElementById("source-link"),
    sourceHost: documentRef.getElementById("source-host"),
    timeline: documentRef.getElementById("timeline"),
    actionChips: documentRef.getElementById("action-chips"),
    composerLabel: documentRef.getElementById("composer-label"),
    messageForm: documentRef.getElementById("message-form"),
    messageInput: documentRef.getElementById("message-input"),
    composerError: documentRef.getElementById("composer-error"),
    composerHint: documentRef.getElementById("composer-hint"),
    turnMeter: documentRef.getElementById("turn-meter"),
    sendButton: documentRef.getElementById("send-button"),
    sendLabel: documentRef.getElementById("send-label"),
  };
}

/** Render a supplied model into a Side Panel document for production and DOM tests. */
export function renderSidePanel(documentRef, model, dependencies = {}) {
  return render(sidePanelElements(documentRef), model, dependencies);
}

/** Send one Workspace turn while retaining composer input until canonical success. */
async function submitMessage(elements, model, dependencies) {
  const message = elements.messageInput.value.trim();
  if (!message || !model.tabId || !model.selectedActionId || model.loading) return;
  const requestTabId = model.tabId;
  const requestActionId = model.selectedActionId;
  const view = workspaceView(model.state || {}, model.lang, model.uiLanguage);
  if (!view.canSend) return;

  model.loading = true;
  model.error = null;
  model.retry = () => elements.messageForm.requestSubmit();
  render(elements, model, dependencies);
  try {
    const response = await sendRuntime({
      type: WORKSPACE_SEND,
      tabId: requestTabId,
      actionId: requestActionId,
      message,
    });
    if (model.tabId !== requestTabId) return;
    if (!response?.ok) {
      model.error = workspaceResponseError(response, view.strings.retryFallback);
      return;
    }
    model.state = response.state;
    model.lang = response.lang || model.lang;
    model.selectedActionId = response.state?.selectedActionId || model.selectedActionId;
    elements.messageInput.value = "";
  } catch (error) {
    if (model.tabId !== requestTabId) return;
    model.error = workspaceResponseError(
      { error: error?.message || view.strings.retryFallback },
      view.strings.retryFallback
    );
  } finally {
    if (model.tabId === requestTabId) {
      model.loading = false;
      render(elements, model, dependencies);
      if (!isUpdateRequired(model.error)) elements.messageInput.focus();
    }
  }
}

/** Reload one tab's Workspace while ignoring responses superseded by a newer tab switch. */
async function loadWorkspaceForTab(elements, model, tabId, dependencies) {
  model.tabId = tabId;
  model.state = null;
  model.selectedActionId = null;
  model.renderedHistoryCount = -1;
  model.loading = !!tabId;
  model.error = null;
  model.retry = () => loadWorkspaceForTab(elements, model, tabId, dependencies).catch(() => {});
  render(elements, model, dependencies);
  if (!tabId) return;

  try {
    const response = await sendRuntime({ type: WORKSPACE_GET, tabId });
    if (model.tabId !== tabId) return;
    if (response?.ok) {
      model.state = response.state;
      model.lang = response.lang || "browser";
      model.selectedActionId = response.state?.selectedActionId || null;
    } else {
      const locale = resolveUiLang(model.lang, model.uiLanguage);
      model.error = workspaceResponseError(response, COPY[locale].retryFallback);
    }
  } catch (error) {
    if (model.tabId !== tabId) return;
    const locale = resolveUiLang(model.lang, model.uiLanguage);
    model.error = workspaceResponseError(
      { error: error?.message || COPY[locale].retryFallback },
      COPY[locale].retryFallback
    );
  } finally {
    if (model.tabId === tabId) {
      model.loading = false;
      render(elements, model, dependencies);
      if (model.state && !isUpdateRequired(model.error)) elements.messageInput.focus();
    }
  }
}

/** Load the active Workspace and install accessible composer interactions. */
async function initSidePanel() {
  const elements = sidePanelElements(document);
  const dependencies = {};
  const model = {
    tabId: await activeTabId(),
    state: null,
    lang: "browser",
    uiLanguage: chrome.i18n.getUILanguage() || "en",
    selectedActionId: null,
    renderedHistoryCount: -1,
    loading: false,
    error: null,
    retry: null,
  };
  model.retry = () => elements.messageForm.requestSubmit();
  elements.messageInput.addEventListener("input", () => {
    updateComposer(
      elements,
      model,
      workspaceView(model.state || {}, model.lang, model.uiLanguage)
    );
  });
  elements.messageInput.addEventListener("keydown", (event) => {
    if (shouldSubmitMessage(event)) {
      event.preventDefault();
      elements.messageForm.requestSubmit();
    }
  });
  elements.messageForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage(elements, model, dependencies);
  });
  render(elements, model, dependencies);

  /** Reload lifecycle changes and surface operation errors for the active tab. */
  const onWorkspaceMessage = (message) => {
    const targetTabId = workspaceLifecycleTarget(message, model.tabId);
    if (targetTabId !== null) {
      loadWorkspaceForTab(elements, model, targetTabId, dependencies).catch(() => {});
      return;
    }
    const isActiveError = !message?.tabId || message.tabId === model.tabId;
    if (
      isActiveError
      && (
        message?.type === "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED"
        || message?.type === "AGENT_BRIDGE_WORKSPACE_ERROR"
      )
    ) {
      model.error = workspaceResponseError(message);
      model.loading = false;
      model.retry = () => elements.messageForm.requestSubmit();
      render(elements, model, dependencies);
    }
  };
  /** Follow the active browser tab even when it has no established Workspace. */
  const onTabActivated = ({ tabId }) => {
    loadWorkspaceForTab(elements, model, tabId, dependencies).catch(() => {});
  };
  /** Release long-lived extension listeners when Chrome destroys this panel document. */
  const cleanup = () => {
    chrome.runtime.onMessage.removeListener(onWorkspaceMessage);
    chrome.tabs.onActivated.removeListener(onTabActivated);
  };
  chrome.runtime.onMessage.addListener(onWorkspaceMessage);
  chrome.tabs.onActivated.addListener(onTabActivated);
  window.addEventListener("unload", cleanup, { once: true });

  await loadWorkspaceForTab(elements, model, model.tabId, dependencies);
}

// Node tests import pure render boundaries without a DOM or Extension runtime.
if (typeof document !== "undefined" && typeof chrome !== "undefined") {
  initSidePanel().catch(() => {});
}
