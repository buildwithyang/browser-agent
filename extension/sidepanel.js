import { renderMarkdown } from "./markdown.js";
import { canSendUserMessage } from "./workspace.js";

export const WORKSPACE_GET = "AGENT_BRIDGE_WORKSPACE_GET";
export const WORKSPACE_SEND = "AGENT_BRIDGE_WORKSPACE_SEND";
export const WORKSPACE_UPDATED = "AGENT_BRIDGE_WORKSPACE_UPDATED";
export const WORKSPACE_RESET = "AGENT_BRIDGE_WORKSPACE_RESET";
export const WORKSPACE_STREAM = "AGENT_BRIDGE_WORKSPACE_STREAM";

const COPY = {
  en: {
    workspace: "Shared Workspace",
    noPage: "No active page",
    offlineTitle: "No active Workspace",
    offline: "Open a Quick Insight Action on a page to start this conversation.",
    emptyTitle: "Start with a clear task",
    noHistory: "Choose an Action below, then say what you want to understand or change.",
    loadingWorkspace: "Loading Workspace",
    loadingWorkspaceBody: "Restoring the conversation for this page…",
    loading: "Working",
    streamFailed: "Generation failed. Your input was restored.",
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
    copyFailed: "Copy failed",
    openCv: "Open CV",
    updateMessage: "Update Agent Bridge to continue.",
    updateGateway: "If this still appears after updating, check the Gateway deployment.",
    updateLink: "Open Chrome Web Store",
  },
  zh: {
    workspace: "共享对话",
    noPage: "没有活动页面",
    offlineTitle: "尚未打开 Workspace",
    offline: "请先在网页的 Quick Insight 中选择一个 Action，开始对话。",
    emptyTitle: "从一个明确的任务开始",
    noHistory: "选择下方 Action，然后说明你想知道或修改什么。",
    loadingWorkspace: "正在加载 Workspace",
    loadingWorkspaceBody: "正在恢复当前页面的对话…",
    loading: "处理中",
    streamFailed: "生成失败，已恢复你的输入。",
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
    copyFailed: "复制失败",
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
  if (currentTabId === null || currentTabId === undefined) return null;
  if (message?.type === WORKSPACE_UPDATED && message.tabId === currentTabId) {
    return currentTabId;
  }
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

/** Apply the composer keyboard contract to one real DOM event and form. */
export function handleComposerKeydown(event, form) {
  if (!shouldSubmitMessage(event)) return false;
  event.preventDefault();
  form.requestSubmit();
  return true;
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

/** Send through an injected deterministic transport or the Extension runtime. */
function sendRuntimeWith(dependencies, message) {
  if (typeof dependencies?.sendRuntime === "function") {
    return dependencies.sendRuntime(message);
  }
  return sendRuntime(message);
}

/** Advance the UI generation and optionally invalidate pending SEND/load ownership. */
function advanceOperationGeneration(model, cancelPendingSend = false) {
  const generation = (Number.isInteger(model.operationGeneration)
    ? model.operationGeneration
    : 0) + 1;
  model.operationGeneration = generation;
  if (cancelPendingSend) {
    model.pendingSendGeneration = null;
    model.latestLoadGeneration = null;
  }
  return generation;
}

/** Return the monotonic revision of transient stream identity and content. */
function currentStreamEpoch(model) {
  return Number.isInteger(model.streamEpoch) ? model.streamEpoch : 0;
}

/** Advance the transient stream revision after one accepted identity/content change. */
function advanceStreamEpoch(model) {
  model.streamEpoch = currentStreamEpoch(model) + 1;
  return model.streamEpoch;
}

/** Start one load generation, invalidating prior loads and identity-bound SENDs on tab change. */
function beginLoadOperation(model, tabId, cancelPendingSend = false) {
  const tabChanged = model.tabId !== tabId;
  const generation = advanceOperationGeneration(
    model,
    cancelPendingSend || tabChanged
  );
  model.latestLoadGeneration = tabId ? generation : null;
  return Object.freeze({
    generation,
    tabId,
    tabChanged,
    streamEpoch: currentStreamEpoch(model),
  });
}

/** Return whether one load generation is still latest for its captured tab. */
function isLatestLoadOperation(model, operation) {
  return model.tabId === operation.tabId
    && model.operationGeneration === operation.generation;
}

/** Return whether this is the newest load even after an older SEND has settled. */
function isLatestTrackedLoadOperation(model, operation) {
  return model.tabId === operation.tabId
    && model.latestLoadGeneration === operation.generation;
}

/** Return whether one load still owns state application and its finally block. */
function isCurrentLoadOperation(model, operation) {
  return isLatestLoadOperation(model, operation)
    && !model.pendingSendGeneration;
}

/** Start one SEND generation that invalidates every previously started load. */
function beginSendOperation(model, tabId, operationId) {
  const generation = advanceOperationGeneration(model);
  model.latestLoadGeneration = null;
  model.pendingSendGeneration = generation;
  return Object.freeze({
    generation,
    operationId,
    tabId,
    resourceUrl: typeof model.state?.resourceUrl === "string"
      ? model.state.resourceUrl
      : "",
  });
}

/** Settle SEND state while preserving ownership of a newer lifecycle load. */
function settleSendOperation(model, operation) {
  if (
    model.tabId !== operation.tabId
    || model.pendingSendGeneration !== operation.generation
    || model.state?.resourceUrl !== operation.resourceUrl
  ) {
    return null;
  }
  const generation = advanceOperationGeneration(model);
  model.pendingSendGeneration = null;
  return Object.freeze({ generation, tabId: operation.tabId });
}

/** Return whether two non-empty canonical state URLs cross a Workspace resource boundary. */
function isResourceSwitch(currentState, incomingState) {
  const currentUrl = typeof currentState?.resourceUrl === "string"
    ? currentState.resourceUrl
    : "";
  const incomingUrl = typeof incomingState?.resourceUrl === "string"
    ? incomingState.resourceUrl
    : "";
  return !!currentUrl && !!incomingUrl && currentUrl !== incomingUrl;
}

/** Promote a latest resource-switching load above pending SEND work. */
function promoteResourceSwitchLoad(model, operation) {
  if (
    !isLatestLoadOperation(model, operation)
    && !isLatestTrackedLoadOperation(model, operation)
  ) {
    return null;
  }
  const generation = advanceOperationGeneration(model, true);
  return Object.freeze({ generation, tabId: operation.tabId });
}

/** Return whether one settled operation still owns final state rendering. */
function isCurrentSettledOperation(model, operation) {
  return !!operation
    && model.tabId === operation.tabId
    && model.operationGeneration === operation.generation;
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
async function copyTextValue(text, dependencies = {}, windowRef) {
  if (typeof dependencies.copyText === "function") {
    await dependencies.copyText(text);
    return;
  }
  const clipboard = windowRef?.navigator?.clipboard;
  if (!clipboard?.writeText) throw new Error("Clipboard API is unavailable");
  await clipboard.writeText(text);
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
    copyButton.setAttribute("aria-live", "polite");
    copyButton.addEventListener("click", async () => {
      copyButton.disabled = true;
      try {
        await copyTextValue(attachment.content, dependencies, documentRef.defaultView);
        copyButton.textContent = view.strings.copied;
        copyButton.setAttribute("aria-label", `${view.strings.copied}: ${attachment.title}`);
      } catch {
        copyButton.textContent = view.strings.copyFailed;
        copyButton.setAttribute("aria-label", `${view.strings.copyFailed}: ${attachment.title}`);
      } finally {
        const scheduleRestore = typeof dependencies.setTimeout === "function"
          ? dependencies.setTimeout
          : documentRef.defaultView.setTimeout.bind(documentRef.defaultView);
        scheduleRestore(() => {
          copyButton.disabled = false;
          copyButton.textContent = view.strings.copy;
          copyButton.setAttribute("aria-label", `${view.strings.copy}: ${attachment.title}`);
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

/** Render the optimistic User row and transient Assistant state after canonical history. */
function renderPendingTurn(elements, pendingTurn, view, dependencies) {
  if (typeof pendingTurn?.userText === "string") {
    const userMessage = renderHistoryMessage(elements.documentRef, {
      role: "user",
      content: pendingTurn.userText,
      created_at: pendingTurn.createdAt,
      attachments: [],
    }, view, dependencies);
    userMessage.classList.add("transient");
    elements.timeline.append(userMessage);
  }

  const assistantMessage = renderHistoryMessage(elements.documentRef, {
    role: "assistant",
    content: pendingTurn.markdown || "",
    created_at: pendingTurn.createdAt,
    attachments: [],
  }, view, dependencies);
  assistantMessage.classList.add(
    "transient",
    pendingTurn.status === "failed" ? "failed" : "pending"
  );
  const status = textElement(
    elements.documentRef,
    "div",
    "stream-status",
    pendingTurn.status === "failed" ? view.strings.streamFailed : `${view.strings.loading}…`
  );
  if (pendingTurn.status === "failed") status.setAttribute("role", "status");
  else status.setAttribute("aria-hidden", "true");
  assistantMessage.querySelector(".message-surface")?.append(status);
  elements.timeline.append(assistantMessage);
}

/** Build one non-message Timeline notice for a specific Workspace connection state. */
function timelineNotice(documentRef, state, icon, title, body) {
  const notice = documentRef.createElement("div");
  notice.className = "timeline-empty-state";
  notice.dataset.state = state;
  const mark = textElement(documentRef, "span", "timeline-empty-mark", icon);
  mark.setAttribute("aria-hidden", "true");
  notice.append(
    mark,
    textElement(documentRef, "strong", "timeline-empty-title", title),
    textElement(documentRef, "p", "timeline-empty-body", body)
  );
  return notice;
}

/** Render the canonical chronological history as the timeline's only content source. */
function renderTimeline(elements, model, view, dependencies) {
  elements.timeline.replaceChildren();
  elements.timeline.setAttribute("aria-busy", String(!!model.loading));
  if (!model.state) {
    elements.timeline.append(
      model.loading
        ? timelineNotice(
          elements.documentRef,
          "loading",
          "…",
          view.strings.loadingWorkspace,
          view.strings.loadingWorkspaceBody
        )
        : timelineNotice(
          elements.documentRef,
          "disconnected",
          "↗",
          view.strings.offlineTitle,
          view.strings.offline
        )
    );
    return;
  }
  if (!view.histories.length && !model.pendingTurn) {
    elements.timeline.append(
      timelineNotice(
        elements.documentRef,
        "connected-empty",
        "✦",
        view.strings.emptyTitle,
        view.strings.noHistory
      )
    );
    return;
  }
  for (const history of view.histories) {
    elements.timeline.append(
      renderHistoryMessage(elements.documentRef, history, view, dependencies)
    );
  }
  if (model.pendingTurn) {
    renderPendingTurn(elements, model.pendingTurn, view, dependencies);
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
  const renderedTurnCount = view.histories.length + (model.pendingTurn ? 2 : 0);
  if (renderedTurnCount > priorCount) {
    elements.timeline.scrollTop = elements.timeline.scrollHeight;
  }
  model.renderedHistoryCount = renderedTurnCount;
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

/** Clear unscoped UI/model state at one owner, tab, or canonical resource boundary. */
function clearWorkspaceTransient(elements, model, dependencies = {}) {
  cancelStreamRender(model, dependencies);
  elements.messageInput.value = "";
  model.pendingTurn = null;
  model.state = null;
  model.selectedActionId = null;
  model.renderedHistoryCount = -1;
  model.error = null;
}

/** Cancel one queued transient Markdown paint at a Workspace identity boundary. */
function cancelStreamRender(model, dependencies = {}) {
  if (model.streamRenderTimer == null) return;
  const cancel = typeof dependencies.clearTimeout === "function"
    ? dependencies.clearTimeout
    : globalThis.clearTimeout;
  cancel(model.streamRenderTimer);
  model.streamRenderTimer = null;
}

/** Coalesce cumulative Markdown snapshots into at most one paint every 50 milliseconds. */
function scheduleStreamRender(model, renderNow, dependencies = {}) {
  if (model.streamRenderTimer != null) return;
  const schedule = typeof dependencies.setTimeout === "function"
    ? dependencies.setTimeout
    : globalThis.setTimeout;
  model.streamRenderTimer = schedule(() => {
    model.streamRenderTimer = null;
    renderNow();
  }, 50);
}

/** Return whether one snapshot belongs to the visible Workspace and current transient operation. */
function isCurrentStreamSnapshot(model, snapshot) {
  const canonicalResourceUrl = typeof model.state?.resourceUrl === "string"
    ? model.state.resourceUrl
    : "";
  const awaitingInitialWorkspace = !canonicalResourceUrl
    && model.loading
    && model.latestLoadGeneration != null;
  if (
    !snapshot
    || snapshot.tabId !== model.tabId
    || typeof snapshot.operationId !== "string"
    || typeof snapshot.resourceUrl !== "string"
    || (!awaitingInitialWorkspace && snapshot.resourceUrl !== canonicalResourceUrl)
    || !Number.isInteger(snapshot.sequence)
  ) {
    return false;
  }
  if (!model.pendingTurn) return true;
  return snapshot.operationId === model.pendingTurn.operationId
    && snapshot.tabId === model.pendingTurn.tabId
    && snapshot.resourceUrl === model.pendingTurn.resourceUrl
    && snapshot.sequence > model.pendingTurn.sequence;
}

/** Convert one owner-scoped Background snapshot into a non-persistent Side Panel turn. */
function pendingTurnFromSnapshot(snapshot) {
  return {
    operationId: snapshot.operationId,
    tabId: snapshot.tabId,
    resourceUrl: snapshot.resourceUrl,
    userText: typeof snapshot.submittedMessage === "string"
      ? snapshot.submittedMessage
      : null,
    createdAt: snapshot.createdAt || new Date().toISOString(),
    sequence: snapshot.sequence,
    stage: snapshot.stage || null,
    markdown: typeof snapshot.markdown === "string" ? snapshot.markdown : "",
    status: "pending",
    inputRestorationHandled: false,
  };
}

/** Restore an owner-scoped pending GET snapshot without writing it into canonical state. */
function restorePendingTurn(model, snapshot, loadOperation = null) {
  const streamAdvancedDuringLoad = !!loadOperation
    && currentStreamEpoch(model) !== loadOperation.streamEpoch;
  const current = model.pendingTurn;
  if (!snapshot) {
    if (streamAdvancedDuringLoad) return false;
    if (model.pendingTurn) advanceStreamEpoch(model);
    model.pendingTurn = null;
    return false;
  }
  if (!isCurrentStreamSnapshot({ ...model, pendingTurn: null }, snapshot)) return false;
  if (
    current
    && current.operationId === snapshot.operationId
    && current.tabId === snapshot.tabId
    && current.resourceUrl === snapshot.resourceUrl
    && snapshot.sequence <= current.sequence
  ) {
    return false;
  }
  if (
    streamAdvancedDuringLoad
    && (
      !current
      || current.operationId !== snapshot.operationId
      || current.tabId !== snapshot.tabId
      || current.resourceUrl !== snapshot.resourceUrl
    )
  ) {
    return false;
  }
  const next = pendingTurnFromSnapshot(snapshot);
  if (current?.operationId === snapshot.operationId) {
    next.userText = current.userText ?? next.userText;
    next.inputRestorationHandled = !!current.inputRestorationHandled;
  }
  model.pendingTurn = next;
  advanceStreamEpoch(model);
  return true;
}

/** Retain a failed Assistant row and restore the exact submitted composer text. */
function failPendingTurn(
  elements,
  model,
  message,
  dependencies = {},
  expectedOperationId = null
) {
  const pendingTurn = model.pendingTurn;
  if (
    !pendingTurn
    || (expectedOperationId && pendingTurn.operationId !== expectedOperationId)
  ) {
    return false;
  }
  cancelStreamRender(model, dependencies);
  pendingTurn.status = "failed";
  model.loading = false;
  if (!pendingTurn.inputRestorationHandled) {
    if (!elements.messageInput.value && typeof pendingTurn.userText === "string") {
      elements.messageInput.value = pendingTurn.userText;
    }
    // One failure signal owns restoration; later settlements must preserve subsequent drafts.
    pendingTurn.inputRestorationHandled = true;
  }
  if (message) model.error = workspaceResponseError({ error: message });
  render(elements, model, dependencies);
  return true;
}

/** Start an authoritative canonical reload after a terminal stream completion. */
function reloadCompletedWorkspace(elements, model, snapshot, dependencies = {}) {
  const options = { expectedResourceUrl: snapshot.resourceUrl };
  const reload = typeof dependencies.reloadWorkspace === "function"
    ? dependencies.reloadWorkspace
    : (tabId, reloadOptions) => loadWorkspaceForTab(
      elements,
      model,
      tabId,
      dependencies,
      reloadOptions
    );
  Promise.resolve(reload(snapshot.tabId, options)).catch(() => {});
}

/** Reduce one cumulative stream runtime message while rejecting stale identity or sequence data. */
export function handleWorkspaceStreamMessage(elements, model, message, dependencies = {}) {
  if (message?.type !== WORKSPACE_STREAM || message.stale === true) return false;
  if (!["started", "status", "delta", "completed", "failed", "interrupted"].includes(
    message.eventType
  )) {
    return false;
  }
  const snapshot = message.snapshot;
  if (!isCurrentStreamSnapshot(model, snapshot)) return false;

  if (!model.pendingTurn) model.pendingTurn = pendingTurnFromSnapshot(snapshot);
  else {
    // Snapshots are cumulative; replacement avoids token concatenation and keeps reducer idempotent.
    model.pendingTurn.sequence = snapshot.sequence;
    model.pendingTurn.stage = snapshot.stage || model.pendingTurn.stage;
    model.pendingTurn.markdown = typeof snapshot.markdown === "string"
      ? snapshot.markdown
      : model.pendingTurn.markdown;
    if (model.pendingTurn.userText === null && typeof snapshot.submittedMessage === "string") {
      model.pendingTurn.userText = snapshot.submittedMessage;
    }
    if (snapshot.createdAt) model.pendingTurn.createdAt = snapshot.createdAt;
  }
  advanceStreamEpoch(model);

  if (message.eventType === "completed") {
    cancelStreamRender(model, dependencies);
    model.pendingTurn = null;
    render(elements, model, dependencies);
    if (!model.pendingSendGeneration) {
      reloadCompletedWorkspace(elements, model, snapshot, dependencies);
    }
    return true;
  }
  if (message.eventType === "failed" || message.eventType === "interrupted") {
    return failPendingTurn(elements, model, null, dependencies);
  }
  scheduleStreamRender(model, () => render(elements, model, dependencies), dependencies);
  return true;
}

/** Render a supplied model into a Side Panel document for production and DOM tests. */
export function renderSidePanel(documentRef, model, dependencies = {}) {
  return render(sidePanelElements(documentRef), model, dependencies);
}

/** Send one Workspace turn with an optimistic, non-persistent transient presentation. */
export async function submitMessage(elements, model, dependencies = {}) {
  const submittedMessage = elements.messageInput.value;
  const message = submittedMessage.trim();
  if (!message || !model.tabId || !model.selectedActionId || model.loading) return;
  const requestTabId = model.tabId;
  const requestActionId = model.selectedActionId;
  const view = workspaceView(model.state || {}, model.lang, model.uiLanguage);
  if (!view.canSend) return;

  const randomUUID = typeof dependencies.randomUUID === "function"
    ? dependencies.randomUUID
    : globalThis.crypto.randomUUID.bind(globalThis.crypto);
  const operationId = randomUUID();
  const createdAt = typeof dependencies.now === "function"
    ? dependencies.now()
    : new Date().toISOString();
  model.pendingTurn = {
    operationId,
    tabId: requestTabId,
    resourceUrl: model.state?.resourceUrl || "",
    userText: submittedMessage,
    createdAt,
    sequence: -1,
    stage: null,
    markdown: "",
    status: "pending",
    inputRestorationHandled: false,
  };
  advanceStreamEpoch(model);
  elements.messageInput.value = "";
  model.loading = true;
  model.error = null;
  model.retry = () => elements.messageForm.requestSubmit();
  const operation = beginSendOperation(model, requestTabId, operationId);
  let settledOperation = null;
  render(elements, model, dependencies);
  try {
    const response = await sendRuntimeWith(dependencies, {
      type: WORKSPACE_SEND,
      tabId: requestTabId,
      actionId: requestActionId,
      message: submittedMessage,
      operationId,
    });
    settledOperation = settleSendOperation(model, operation);
    if (!settledOperation) return;
    if (response?.stale === true) {
      failPendingTurn(
        elements,
        model,
        response.error || view.strings.retryFallback,
        dependencies,
        operation.operationId
      );
      return;
    }
    model.retry = () => elements.messageForm.requestSubmit();
    if (!response?.ok) {
      model.error = workspaceResponseError(response, view.strings.retryFallback);
      failPendingTurn(elements, model, null, dependencies, operation.operationId);
      return;
    }
    cancelStreamRender(model, dependencies);
    model.pendingTurn = null;
    model.state = response.state;
    model.lang = response.lang || model.lang;
    model.selectedActionId = response.state?.selectedActionId || model.selectedActionId;
  } catch (error) {
    settledOperation = settleSendOperation(model, operation);
    if (!settledOperation) return;
    model.retry = () => elements.messageForm.requestSubmit();
    model.error = workspaceResponseError(
      { error: error?.message || view.strings.retryFallback },
      view.strings.retryFallback
    );
    failPendingTurn(elements, model, null, dependencies, operation.operationId);
  } finally {
    if (isCurrentSettledOperation(model, settledOperation)) {
      model.loading = model.latestLoadGeneration != null;
      render(elements, model, dependencies);
      if (!model.loading && !isUpdateRequired(model.error)) {
        elements.messageInput.focus();
      }
    }
  }
}

/** Reload one tab's Workspace while ignoring responses superseded by a newer tab switch. */
export async function loadWorkspaceForTab(
  elements,
  model,
  tabId,
  dependencies = {},
  options = {}
) {
  const expectedResourceUrl = typeof options.expectedResourceUrl === "string"
    ? options.expectedResourceUrl
    : "";
  if (expectedResourceUrl && model.state?.resourceUrl !== expectedResourceUrl) return;
  const operation = beginLoadOperation(model, tabId, !!options.cancelPendingSend);
  const clearState = operation.tabChanged || !!options.clearState;
  model.tabId = tabId;
  if (clearState) clearWorkspaceTransient(elements, model, dependencies);
  model.loading = !!tabId;
  model.error = null;
  model.retry = () => loadWorkspaceForTab(elements, model, tabId, dependencies).catch(() => {});
  render(elements, model, dependencies);
  if (!tabId) return;

  let completionOperation = null;
  try {
    const response = await sendRuntimeWith(dependencies, { type: WORKSPACE_GET, tabId });
    if (
      !isLatestLoadOperation(model, operation)
      && !isLatestTrackedLoadOperation(model, operation)
    ) {
      return;
    }
    if (
      expectedResourceUrl
      && (
        model.state?.resourceUrl !== expectedResourceUrl
        || (response?.ok && response.state?.resourceUrl !== expectedResourceUrl)
      )
    ) {
      return;
    }
    if (response?.ok) {
      if (isResourceSwitch(model.state, response.state)) {
        completionOperation = promoteResourceSwitchLoad(model, operation);
        if (!completionOperation) return;
        clearWorkspaceTransient(elements, model, dependencies);
      } else {
        if (!isCurrentLoadOperation(model, operation)) return;
        completionOperation = operation;
      }
      model.state = response.state;
      model.lang = response.lang || "browser";
      model.selectedActionId = response.state?.selectedActionId || null;
      if (
        model.pendingTurn
        && model.pendingTurn.resourceUrl !== response.state?.resourceUrl
      ) {
        cancelStreamRender(model, dependencies);
        model.pendingTurn = null;
        advanceStreamEpoch(model);
      }
      restorePendingTurn(model, response.pendingStream, operation);
    } else {
      if (!isCurrentLoadOperation(model, operation)) return;
      completionOperation = operation;
      const locale = resolveUiLang(model.lang, model.uiLanguage);
      model.error = workspaceResponseError(response, COPY[locale].retryFallback);
    }
  } catch (error) {
    if (!isCurrentLoadOperation(model, operation)) return;
    completionOperation = operation;
    const locale = resolveUiLang(model.lang, model.uiLanguage);
    model.error = workspaceResponseError(
      { error: error?.message || COPY[locale].retryFallback },
      COPY[locale].retryFallback
    );
  } finally {
    const releasedLatestLoad = model.latestLoadGeneration === operation.generation;
    if (releasedLatestLoad) {
      model.latestLoadGeneration = null;
    }
    if (isCurrentSettledOperation(model, completionOperation)) {
      model.loading = false;
      render(elements, model, dependencies);
      if (model.state && !isUpdateRequired(model.error)) elements.messageInput.focus();
    } else if (releasedLatestLoad && !model.pendingSendGeneration) {
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
    operationGeneration: 0,
    latestLoadGeneration: null,
    pendingSendGeneration: null,
    pendingTurn: null,
    streamRenderTimer: null,
    streamEpoch: 0,
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
    handleComposerKeydown(event, elements.messageForm);
  });
  elements.messageForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage(elements, model, dependencies);
  });
  render(elements, model, dependencies);

  /** Reload lifecycle changes and surface operation errors for the active tab. */
  const onWorkspaceMessage = (message) => {
    if (message?.type === WORKSPACE_STREAM) {
      handleWorkspaceStreamMessage(elements, model, message, dependencies);
      return;
    }
    const targetTabId = workspaceLifecycleTarget(message, model.tabId);
    if (targetTabId !== null) {
      const reset = message.type === WORKSPACE_RESET;
      loadWorkspaceForTab(elements, model, targetTabId, dependencies, {
        cancelPendingSend: reset,
        clearState: reset,
      }).catch(() => {});
      return;
    }
    const isActiveError = !message?.tabId || message.tabId === model.tabId;
    if (
      isActiveError
      && message?.stale !== true
      && (
        message?.type === "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED"
        || message?.type === "AGENT_BRIDGE_WORKSPACE_ERROR"
      )
    ) {
      advanceOperationGeneration(model, true);
      model.error = workspaceResponseError(message);
      model.loading = false;
      model.retry = () => elements.messageForm.requestSubmit();
      if (!failPendingTurn(elements, model, null, dependencies)) {
        render(elements, model, dependencies);
      }
    }
  };
  /** Follow the active browser tab even when it has no established Workspace. */
  const onTabActivated = ({ tabId }) => {
    loadWorkspaceForTab(elements, model, tabId, dependencies).catch(() => {});
  };
  /** Release long-lived extension listeners when Chrome destroys this panel document. */
  const cleanup = () => {
    cancelStreamRender(model, dependencies);
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
