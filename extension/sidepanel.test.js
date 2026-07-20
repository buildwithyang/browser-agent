import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { JSDOM } from "jsdom";

import * as sidepanel from "./sidepanel.js";

const RESOURCE_URL = "https://www.linkedin.com/jobs/view/123";
const OTHER_RESOURCE_URL = "https://www.linkedin.com/jobs/view/456";
const COVER_LETTER_MARKDOWN = [
  "# Application",
  "",
  "Dear **Hiring Manager**",
  "",
  "<script>window.__attachmentXss = true</script>",
].join("\n");

/** Return a deterministic UUID-shaped identifier for one fixture category and index. */
function fixtureId(category, index) {
  return `${category}0000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
}

/** Build one complete protocol-v2 message fixture. */
function message(index, overrides = {}) {
  const role = overrides.role || (index % 2 === 0 ? "user" : "assistant");
  return {
    id: fixtureId("3", index + 1),
    role,
    content: role === "user" ? "question" : "answer",
    action_id: "analyze",
    created_at: `2026-07-20T10:0${index}:00Z`,
    attachments: [],
    ...overrides,
  };
}

/** Build one immutable Attachment fixture. */
function attachment({
  type = "cover_letter",
  content = COVER_LETTER_MARKDOWN,
  idIndex = type === "cv" ? 2 : 1,
  version = 1,
} = {}) {
  return {
    id: fixtureId("2", idIndex),
    artifact_id: fixtureId("1", type === "cv" ? 2 : 1),
    version,
    type,
    title: type === "cv" ? "Tailored CV" : "Cover Letter",
    content,
  };
}

/** Build one valid schema-v2 Workspace with optional state overrides. */
function workspace(overrides = {}) {
  return {
    schemaVersion: 2,
    resourceUrl: RESOURCE_URL,
    pageTitle: "Platform Engineer",
    quickInsight: {
      title: "Strong match",
      cards: [{ type: "score", id: "decision", title: "Decision", score: 87 }],
    },
    actions: [
      { id: "analyze", title: "Analyze" },
      { id: "ask_more", title: "Ask More" },
    ],
    selectedActionId: "analyze",
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    updatedAt: null,
    ...overrides,
  };
}

/** Create a detached Side Panel document from the production HTML. */
async function panelDocument() {
  const html = await readFile(new URL("./sidepanel.html", import.meta.url), "utf8");
  return new JSDOM(html, { url: "https://extension.invalid/sidepanel.html" });
}

/** Render one state through the production renderer with deterministic dependencies. */
async function renderState(state, overrides = {}) {
  assert.equal(typeof sidepanel.renderSidePanel, "function");
  const dom = await panelDocument();
  const copied = [];
  const { dependencies: dependencyOverrides = {}, ...modelOverrides } = overrides;
  const model = {
    state,
    lang: "en",
    uiLanguage: "en-US",
    selectedActionId: state?.selectedActionId || null,
    loading: false,
    error: null,
    ...modelOverrides,
  };
  const elements = sidepanel.renderSidePanel(dom.window.document, model, {
    copyText: async (text) => copied.push(text),
    ...dependencyOverrides,
  });
  return { copied, dom, elements, model };
}

/** Create one manually controlled Promise for operation-ordering tests. */
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

test("manifest declares the Side Panel entry point and release version", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("./manifest.json", import.meta.url), "utf8")
  );
  assert.ok(manifest.permissions.includes("sidePanel"));
  assert.equal(manifest.side_panel.default_path, "sidepanel.html");
  assert.equal(manifest.version, "0.2.0");
});

test("header contains only page identity, source, and an optional match score", async () => {
  const { dom } = await renderState(workspace());
  const { document } = dom.window;
  const header = document.querySelector(".workspace-header");

  assert.equal(header?.querySelector("h1")?.textContent, "Platform Engineer");
  assert.match(header?.querySelector(".source-link")?.textContent || "", /linkedin\.com/);
  assert.equal(header?.querySelector(".match-score")?.textContent, "87 / 100");
  assert.equal(header?.querySelector(".connection-status"), null);
  assert.equal(document.querySelector(".insight-card"), null);
  assert.equal(document.querySelector(".artifact-card"), null);
  assert.equal(document.querySelector(".resume-preview-card"), null);
  assert.doesNotMatch(document.body.textContent, /Business Overview|Role Focus|Strength|Gap|Quick Insight|Latest Artifact/i);

  const withoutScore = await renderState(workspace({ quickInsight: null }));
  assert.equal(
    withoutScore.dom.window.document.querySelector(".match-score:not([hidden])"),
    null
  );
});

test("messages preserve chronology, render roles safely, and show semantic local times", async () => {
  const histories = [
    message(0, { content: "<img src=x onerror=alert(1)> first" }),
    message(1, {
      content: "## Second\n\n**safe**<script>window.__messageXss = true</script>",
    }),
  ];
  const { dom } = await renderState(workspace({ histories }));
  const { document } = dom.window;
  const rendered = [...document.querySelectorAll(".message")];

  assert.deepEqual(
    rendered.map((item) => item.querySelector(".message-content")?.textContent.trim()),
    ["<img src=x onerror=alert(1)> first", "Second\nsafe"]
  );
  assert.equal(rendered[0].querySelector("img"), null, "User content must stay text");
  assert.equal(rendered[1].querySelector("strong")?.textContent, "safe");
  assert.equal(rendered[1].querySelector("script"), null);
  assert.equal(dom.window.__messageXss, undefined);
  assert.equal(document.querySelector(".message-role"), null);
  assert.doesNotMatch(rendered.map((item) => item.textContent).join(" "), /\bYou\b|\bAgent\b|你/);

  const times = [...document.querySelectorAll(".message time")];
  assert.equal(times.length, histories.length);
  for (const [index, time] of times.entries()) {
    assert.match(time.textContent, /^\d{2}:\d{2}$/);
    assert.equal(time.getAttribute("datetime"), histories[index].created_at);
    assert.ok(time.title.length > time.textContent.length);
  }
});

test("Cover Letter Attachment stays in its Assistant Message, renders Markdown, and copies source", async () => {
  const item = attachment();
  const histories = [message(1, { content: "Draft ready.", attachments: [item] })];
  const artifacts = {
    cv: null,
    cover_letter: {
      id: item.artifact_id,
      type: item.type,
      version: item.version,
      title: item.title,
      draft: item.content,
      attachment: item,
    },
  };
  const { copied, dom } = await renderState(workspace({ histories, artifacts }));
  const { document } = dom.window;
  const messageNode = document.querySelector(".message.assistant");
  const attachmentNode = messageNode?.querySelector(".attachment.cover-letter");

  assert.ok(attachmentNode);
  assert.equal(document.querySelector(".timeline > .attachment"), null);
  assert.equal(attachmentNode.querySelector("h2")?.textContent, "Cover Letter");
  assert.equal(attachmentNode.querySelector("strong")?.textContent, "Hiring Manager");
  assert.equal(attachmentNode.querySelector("script"), null);
  attachmentNode.querySelector(".attachment-copy")?.click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(copied, [COVER_LETTER_MARKDOWN]);
});

test("historical Attachment versions remain visible and copy their own raw Markdown", async () => {
  const first = attachment({ content: "# Version one", idIndex: 11, version: 1 });
  const second = attachment({ content: "# Version two", idIndex: 12, version: 2 });
  const histories = [
    message(1, { content: "First draft.", attachments: [first] }),
    message(3, { content: "Revised draft.", attachments: [second] }),
  ];
  const artifacts = {
    cv: null,
    cover_letter: {
      id: second.artifact_id,
      type: second.type,
      version: second.version,
      title: second.title,
      draft: second.content,
      attachment: second,
    },
  };
  const { copied, dom } = await renderState(workspace({ histories, artifacts }));
  const attachments = [...dom.window.document.querySelectorAll(".attachment.cover-letter")];

  assert.deepEqual(
    attachments.map((item) => item.querySelector(".attachment-body")?.textContent.trim()),
    ["Version one", "Version two"]
  );
  attachments[0].querySelector(".attachment-copy")?.click();
  attachments[1].querySelector(".attachment-copy")?.click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(copied, ["# Version one", "# Version two"]);
});

test("Cover Letter copy reports Clipboard absence and rejection before restoring", async () => {
  const item = attachment();
  const state = workspace({
    histories: [message(1, { attachments: [item] })],
    artifacts: {
      cv: null,
      cover_letter: {
        id: item.artifact_id,
        type: item.type,
        version: item.version,
        title: item.title,
        draft: item.content,
        attachment: item,
      },
    },
  });

  for (const dependencies of [
    {},
    { copyText: async () => { throw new Error("permission denied"); } },
  ]) {
    const dom = await panelDocument();
    const model = {
      state,
      lang: "en",
      uiLanguage: "en-US",
      selectedActionId: "analyze",
      loading: false,
      error: null,
    };
    let restore = null;
    const elements = sidepanel.renderSidePanel(dom.window.document, model, {
      ...dependencies,
      setTimeout: (callback) => { restore = callback; },
    });
    const button = dom.window.document.querySelector(".attachment-copy");

    button?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(button?.textContent, "Copy failed");
    assert.match(button?.getAttribute("aria-label") || "", /Copy failed/i);
    assert.equal(button?.disabled, true);
    assert.equal(typeof restore, "function");
    restore();
    assert.equal(button?.textContent, "Copy Markdown");
    assert.equal(button?.disabled, false);
    assert.ok(elements.timeline.contains(button));
  }
});

test("CV Attachment opens the response URL safely and Side Panel has no preview constant", async () => {
  const responseUrl = "https://files.example.com/generated/cv-42?signature=response";
  const item = attachment({ type: "cv", content: responseUrl });
  const histories = [message(1, { content: "CV ready.", attachments: [item] })];
  const artifacts = {
    cv: {
      id: item.artifact_id,
      type: item.type,
      version: item.version,
      title: item.title,
      draft: "# Private CV draft",
      attachment: item,
    },
    cover_letter: null,
  };
  const { dom } = await renderState(workspace({ histories, artifacts }));
  const link = dom.window.document.querySelector(".attachment.cv .attachment-open");
  const source = await readFile(new URL("./sidepanel.js", import.meta.url), "utf8");

  assert.equal(link?.href, responseUrl);
  assert.equal(link?.target, "_blank");
  assert.match(link?.rel || "", /noopener/);
  assert.match(link?.rel || "", /noreferrer/);
  assert.doesNotMatch(source, /browser\.buildwithyang\.com/);
  assert.equal("CV_PREVIEW_URL" in sidepanel, false);
});

test("Action chips wrap near the composer and selection never clears shared history", async () => {
  const histories = [message(0), message(1)];
  const { dom, model } = await renderState(workspace({ histories }));
  const { document } = dom.window;
  const chips = [...document.querySelectorAll("#composer .action-chip")];

  assert.equal(chips.length, 2);
  chips[1].click();
  assert.equal(model.selectedActionId, "ask_more");
  assert.equal(document.querySelectorAll(".message").length, histories.length);
  assert.equal(chips[1].getAttribute("aria-pressed"), "true");

  const generic = await renderState(workspace({
    quickInsight: { title: "Page summary", cards: [] },
    actions: [{ id: "ask_more", title: "Ask More" }],
    selectedActionId: "ask_more",
  }));
  assert.deepEqual(
    [...generic.dom.window.document.querySelectorAll(".action-chip")].map((chip) => chip.textContent),
    ["Ask More"]
  );
});

test("update-required and retryable errors render distinct accessible composer states", async () => {
  assert.equal(typeof sidepanel.workspaceResponseError, "function");
  const updateUrl = "https://chromewebstore.google.com/detail/agent-bridge/id";
  const updateError = sidepanel.workspaceResponseError({
    ok: false,
    type: "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED",
    updateUrl,
    requiredVersion: 3,
  });
  const updated = await renderState(workspace(), { error: updateError });
  const updateRegion = updated.dom.window.document.querySelector("#composer-error");
  const updateLink = updateRegion?.querySelector("a");

  assert.equal(updateLink?.href, updateUrl);
  assert.equal(updateLink?.target, "_blank");
  assert.match(updateRegion?.textContent || "", /check the Gateway deployment/i);
  assert.doesNotMatch(updateRegion?.textContent || "", /sign in|log in|expired/i);
  assert.equal(updated.elements.messageInput.disabled, true);

  let retries = 0;
  const retryable = await renderState(workspace(), {
    error: sidepanel.workspaceResponseError({ ok: false, error: "Gateway unavailable" }),
    retry: () => { retries += 1; },
  });
  const retryRegion = retryable.dom.window.document.querySelector("#composer-error");
  assert.match(retryRegion?.textContent || "", /Gateway unavailable/);
  retryRegion?.querySelector("button")?.click();
  assert.equal(retries, 1);
  assert.equal(retryable.elements.messageInput.disabled, false);
});

test("textarea dispatch submits Enter once and preserves native Shift+Enter", async () => {
  assert.equal(typeof sidepanel.handleComposerKeydown, "function");
  const dom = await panelDocument();
  const textarea = dom.window.document.getElementById("message-input");
  const form = dom.window.document.getElementById("message-form");
  let submits = 0;
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    submits += 1;
  });
  textarea?.addEventListener("keydown", (event) => {
    sidepanel.handleComposerKeydown(event, form);
  });

  const enter = new dom.window.KeyboardEvent("keydown", {
    key: "Enter",
    bubbles: true,
    cancelable: true,
  });
  textarea?.dispatchEvent(enter);
  assert.equal(enter.defaultPrevented, true);
  assert.equal(submits, 1);

  const shiftEnter = new dom.window.KeyboardEvent("keydown", {
    key: "Enter",
    shiftKey: true,
    bubbles: true,
    cancelable: true,
  });
  textarea?.dispatchEvent(shiftEnter);
  assert.equal(shiftEnter.defaultPrevented, false);
  assert.equal(submits, 1);
});

test("same-tab load generations allow only the latest response and finally block", async () => {
  assert.equal(typeof sidepanel.loadWorkspaceForTab, "function");
  const { elements, model } = await renderState(null, { tabId: 7 });
  const oldRequest = deferred();
  const newRequest = deferred();
  const requests = [oldRequest, newRequest];
  const dependencies = {
    sendRuntime: () => requests.shift().promise,
  };

  const first = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  const second = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  const oldResponse = workspace({ pageTitle: "Old response" });
  const newResponse = workspace({ pageTitle: "New response" });

  oldRequest.resolve({ ok: true, state: oldResponse, lang: "en" });
  await first;
  assert.equal(model.state, null);
  assert.equal(model.loading, true);

  newRequest.resolve({ ok: true, state: newResponse, lang: "en" });
  await second;
  assert.equal(model.state?.pageTitle, "New response");
  assert.equal(model.loading, false);
});

test("late older same-tab load cannot overwrite a completed newer load", async () => {
  assert.equal(typeof sidepanel.loadWorkspaceForTab, "function");
  const { elements, model } = await renderState(null, { tabId: 7 });
  const oldRequest = deferred();
  const newRequest = deferred();
  const requests = [oldRequest, newRequest];
  const dependencies = { sendRuntime: () => requests.shift().promise };

  const first = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  const second = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  newRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Canonical new" }),
    lang: "en",
  });
  await second;
  oldRequest.resolve({ ok: false, error: "Stale load error" });
  await first;

  assert.equal(model.state?.pageTitle, "Canonical new");
  assert.equal(model.loading, false);
  assert.equal(model.error, null);
});

test("SEND invalidates overlapping GET state and keeps loading until SEND settles", async () => {
  assert.equal(typeof sidepanel.submitMessage, "function");
  assert.equal(typeof sidepanel.loadWorkspaceForTab, "function");
  const initial = workspace({ pageTitle: "Initial" });
  const { elements, model } = await renderState(initial, {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const sendRequest = deferred();
  const getRequest = deferred();
  const dependencies = {
    sendRuntime: (request) => (
      request.type === sidepanel.WORKSPACE_SEND ? sendRequest.promise : getRequest.promise
    ),
  };
  elements.messageInput.value = "Please revise";

  const send = sidepanel.submitMessage(elements, model, dependencies);
  const load = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  getRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Stale GET" }),
    lang: "en",
  });
  await load;
  assert.equal(model.state?.pageTitle, "Initial");
  assert.equal(model.loading, true);

  sendRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Canonical SEND" }),
    lang: "en",
  });
  await send;
  assert.equal(model.state?.pageTitle, "Canonical SEND");
  assert.equal(model.loading, false);
  assert.equal(model.error, null);
});

test("late Workspace updates refresh only the currently active tab", () => {
  assert.equal(sidepanel.workspaceLifecycleTarget({
    type: sidepanel.WORKSPACE_UPDATED,
    tabId: 7,
  }, 8), null, "late tab A update must not switch active tab B");
  assert.equal(sidepanel.workspaceLifecycleTarget({
    type: sidepanel.WORKSPACE_UPDATED,
    tabId: 8,
  }, 8), 8, "active tab B update refreshes B");
  assert.equal(sidepanel.workspaceLifecycleTarget({
    type: sidepanel.WORKSPACE_UPDATED,
    tabId: 8,
  }, null), null, "no active tab means no update-driven tab selection");
  assert.equal(sidepanel.workspaceLifecycleTarget({
    type: sidepanel.WORKSPACE_RESET,
  }, null), null, "global reset cannot manufacture an active tab");
});

test("tab switch and reset generations invalidate earlier loads", async () => {
  assert.equal(typeof sidepanel.loadWorkspaceForTab, "function");
  const { elements, model } = await renderState(workspace({ pageTitle: "Tab A" }), {
    tabId: 7,
  });
  const tabARequest = deferred();
  const tabBRequest = deferred();
  const resetRequest = deferred();
  const requests = [tabARequest, tabBRequest, resetRequest];
  const dependencies = { sendRuntime: () => requests.shift().promise };

  const tabALoad = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  const tabBLoad = sidepanel.loadWorkspaceForTab(elements, model, 8, dependencies);
  tabARequest.resolve({ ok: true, state: workspace({ pageTitle: "Late A" }), lang: "en" });
  await tabALoad;
  assert.equal(model.tabId, 8);
  assert.equal(model.state, null);
  assert.equal(model.loading, true);

  tabBRequest.resolve({ ok: true, state: workspace({ pageTitle: "Tab B" }), lang: "en" });
  await tabBLoad;
  assert.equal(model.state?.pageTitle, "Tab B");

  const resetLoad = sidepanel.loadWorkspaceForTab(elements, model, 8, dependencies, {
    cancelPendingSend: true,
    clearState: true,
  });
  assert.equal(model.state, null);
  resetRequest.resolve({ ok: false, error: "Workspace reset" });
  await resetLoad;
  assert.equal(model.state, null);
  assert.match(model.error?.message || "", /reset/i);
  assert.equal(model.loading, false);
});

test("workspace boundaries clear drafts while same-tab reload preserves them", async () => {
  const { elements, model } = await renderState(workspace({ pageTitle: "Tab A" }), {
    tabId: 7,
  });
  const tabBRequest = deferred();
  const sameTabRequest = deferred();
  const resetRequest = deferred();
  const requests = [tabBRequest, sameTabRequest, resetRequest];
  const dependencies = { sendRuntime: () => requests.shift().promise };

  elements.messageInput.value = "private draft from tab A";
  const tabBLoad = sidepanel.loadWorkspaceForTab(elements, model, 8, dependencies);
  assert.equal(elements.messageInput.value, "", "tab/resource change clears the old draft");
  tabBRequest.resolve({ ok: true, state: workspace({ pageTitle: "Tab B" }), lang: "en" });
  await tabBLoad;

  elements.messageInput.value = "draft still being written on tab B";
  const sameTabLoad = sidepanel.loadWorkspaceForTab(elements, model, 8, dependencies);
  assert.equal(
    elements.messageInput.value,
    "draft still being written on tab B",
    "ordinary same-tab Workspace update preserves the draft"
  );
  sameTabRequest.resolve({ ok: true, state: workspace({ pageTitle: "Tab B refreshed" }), lang: "en" });
  await sameTabLoad;
  assert.equal(elements.messageInput.value, "draft still being written on tab B");

  const resetLoad = sidepanel.loadWorkspaceForTab(elements, model, 8, dependencies, {
    cancelPendingSend: true,
    clearState: true,
  });
  assert.equal(elements.messageInput.value, "", "owner/reset boundary clears the draft");
  resetRequest.resolve({ ok: false, error: "Workspace reset" });
  await resetLoad;
  assert.equal(elements.messageInput.value, "");
});

test("reset-cleared draft stays empty after an invalidated SEND resolves", async () => {
  const { elements, model } = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const sendRequest = deferred();
  const resetRequest = deferred();
  const dependencies = {
    sendRuntime: (request) => (
      request.type === sidepanel.WORKSPACE_SEND ? sendRequest.promise : resetRequest.promise
    ),
  };
  elements.messageInput.value = "owner A private instruction";

  const send = sidepanel.submitMessage(elements, model, dependencies);
  const reset = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies, {
    cancelPendingSend: true,
    clearState: true,
  });
  assert.equal(elements.messageInput.value, "");
  resetRequest.resolve({ ok: true, state: workspace({ pageTitle: "Owner B" }), lang: "en" });
  await reset;
  sendRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Late owner A SEND" }),
    lang: "en",
  });
  await send;

  assert.equal(model.state?.pageTitle, "Owner B");
  assert.equal(elements.messageInput.value, "");
});

test("same-tab canonical resource switch clears the old resource draft", async () => {
  const { elements, model } = await renderState(workspace({ pageTitle: "Resource A" }), {
    tabId: 7,
  });
  const request = deferred();
  const dependencies = { sendRuntime: () => request.promise };
  elements.messageInput.value = "private draft for resource A";

  const load = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  assert.equal(
    elements.messageInput.value,
    "private draft for resource A",
    "the draft remains until the canonical response identifies a new resource"
  );
  request.resolve({
    ok: true,
    state: workspace({
      resourceUrl: OTHER_RESOURCE_URL,
      pageTitle: "Resource B",
      selectedActionId: "ask_more",
    }),
    lang: "en",
  });
  await load;

  assert.equal(model.state?.resourceUrl, OTHER_RESOURCE_URL);
  assert.equal(model.state?.pageTitle, "Resource B");
  assert.equal(model.selectedActionId, "ask_more");
  assert.equal(model.error, null);
  assert.equal(elements.messageInput.value, "");
});

test("same-tab resource B GET supersedes pending resource A SEND", async () => {
  const { elements, model } = await renderState(workspace({ pageTitle: "Resource A" }), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const sendRequest = deferred();
  const getRequest = deferred();
  const dependencies = {
    sendRuntime: (request) => (
      request.type === sidepanel.WORKSPACE_SEND ? sendRequest.promise : getRequest.promise
    ),
  };
  elements.messageInput.value = "resource A private instruction";

  const send = sidepanel.submitMessage(elements, model, dependencies);
  const load = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  getRequest.resolve({
    ok: true,
    state: workspace({ resourceUrl: OTHER_RESOURCE_URL, pageTitle: "Resource B" }),
    lang: "en",
  });
  await load;
  assert.equal(model.state?.resourceUrl, OTHER_RESOURCE_URL);
  assert.equal(elements.messageInput.value, "");
  assert.equal(model.loading, false);

  sendRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Late resource A SEND" }),
    lang: "en",
  });
  await send;
  assert.equal(model.state?.resourceUrl, OTHER_RESOURCE_URL);
  assert.equal(model.state?.pageTitle, "Resource B");
  assert.equal(elements.messageInput.value, "");
});

test("same-tab resource B GET survives resource A SEND settling first", async () => {
  const { elements, model } = await renderState(workspace({ pageTitle: "Resource A" }), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const sendRequest = deferred();
  const getRequest = deferred();
  const dependencies = {
    sendRuntime: (request) => (
      request.type === sidepanel.WORKSPACE_SEND ? sendRequest.promise : getRequest.promise
    ),
  };
  elements.messageInput.value = "resource A private instruction";

  const send = sidepanel.submitMessage(elements, model, dependencies);
  const load = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  sendRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Resource A SEND result" }),
    lang: "en",
  });
  await send;
  assert.equal(model.state?.pageTitle, "Resource A SEND result");

  getRequest.resolve({
    ok: true,
    state: workspace({ resourceUrl: OTHER_RESOURCE_URL, pageTitle: "Resource B" }),
    lang: "en",
  });
  await load;

  assert.equal(model.state?.resourceUrl, OTHER_RESOURCE_URL);
  assert.equal(model.state?.pageTitle, "Resource B");
  assert.equal(elements.messageInput.value, "");
  assert.equal(model.loading, false);
});

test("settled resource A SEND keeps a newer resource load exclusive", async () => {
  const { elements, model } = await renderState(workspace({ pageTitle: "Resource A" }), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const sendRequest = deferred();
  const getRequest = deferred();
  const runtimeTypes = [];
  const dependencies = {
    sendRuntime: (request) => {
      runtimeTypes.push(request.type);
      return request.type === sidepanel.WORKSPACE_SEND
        ? sendRequest.promise
        : getRequest.promise;
    },
  };
  elements.messageInput.value = "resource A private instruction";

  const send = sidepanel.submitMessage(elements, model, dependencies);
  const load = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  sendRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Resource A SEND result" }),
    lang: "en",
  });
  await send;

  assert.equal(model.loading, true);
  assert.equal(elements.messageInput.disabled, true);
  elements.messageInput.value = "must wait for resource B";
  await sidepanel.submitMessage(elements, model, dependencies);
  assert.deepEqual(runtimeTypes, [sidepanel.WORKSPACE_SEND, sidepanel.WORKSPACE_GET]);

  getRequest.resolve({
    ok: true,
    state: workspace({ resourceUrl: OTHER_RESOURCE_URL, pageTitle: "Resource B" }),
    lang: "en",
  });
  await load;
  assert.equal(model.state?.resourceUrl, OTHER_RESOURCE_URL);
  assert.equal(model.loading, false);
});

test("same-resource tracked load releases loading after an older SEND settles", async () => {
  const { elements, model } = await renderState(workspace({ pageTitle: "Resource A" }), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const sendRequest = deferred();
  const getRequest = deferred();
  const dependencies = {
    sendRuntime: (request) => (
      request.type === sidepanel.WORKSPACE_SEND ? sendRequest.promise : getRequest.promise
    ),
  };
  elements.messageInput.value = "resource A private instruction";

  const send = sidepanel.submitMessage(elements, model, dependencies);
  const load = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  sendRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Canonical SEND" }),
    lang: "en",
  });
  await send;
  assert.equal(model.loading, true);

  getRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Stale same-resource GET" }),
    lang: "en",
  });
  await load;
  assert.equal(model.state?.pageTitle, "Canonical SEND");
  assert.equal(model.loading, false);
  assert.equal(elements.messageInput.disabled, false);
});

test("failed tracked load releases loading after an older SEND settles", async () => {
  const { elements, model } = await renderState(workspace({ pageTitle: "Resource A" }), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const sendRequest = deferred();
  const getRequest = deferred();
  const dependencies = {
    sendRuntime: (request) => (
      request.type === sidepanel.WORKSPACE_SEND ? sendRequest.promise : getRequest.promise
    ),
  };
  elements.messageInput.value = "resource A private instruction";

  const send = sidepanel.submitMessage(elements, model, dependencies);
  const load = sidepanel.loadWorkspaceForTab(elements, model, 7, dependencies);
  sendRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Canonical SEND" }),
    lang: "en",
  });
  await send;
  assert.equal(model.loading, true);

  getRequest.resolve({ ok: false, error: "Stale load failure" });
  await load;
  assert.equal(model.state?.pageTitle, "Canonical SEND");
  assert.equal(model.error, null);
  assert.equal(model.loading, false);
  assert.equal(elements.messageInput.disabled, false);
});

test("same-resource and initial same-tab loads do not clear a draft", async () => {
  const sameResourceRequest = deferred();
  const rendered = await renderState(workspace({ pageTitle: "Resource A" }), { tabId: 7 });
  rendered.elements.messageInput.value = "work in progress";
  const sameResourceLoad = sidepanel.loadWorkspaceForTab(
    rendered.elements,
    rendered.model,
    7,
    { sendRuntime: () => sameResourceRequest.promise }
  );
  sameResourceRequest.resolve({
    ok: true,
    state: workspace({ pageTitle: "Resource A refreshed" }),
    lang: "en",
  });
  await sameResourceLoad;
  assert.equal(rendered.elements.messageInput.value, "work in progress");
  assert.equal(rendered.model.state?.pageTitle, "Resource A refreshed");

  const initialRequest = deferred();
  const initial = await renderState(null, { tabId: 7 });
  initial.elements.messageInput.value = "draft before initial state arrives";
  const initialLoad = sidepanel.loadWorkspaceForTab(
    initial.elements,
    initial.model,
    7,
    { sendRuntime: () => initialRequest.promise }
  );
  initialRequest.resolve({ ok: true, state: workspace(), lang: "en" });
  await initialLoad;
  assert.equal(initial.model.state?.resourceUrl, RESOURCE_URL);
  assert.equal(initial.elements.messageInput.value, "draft before initial state arrives");
});

test("light responsive CSS contains horizontal overflow and keeps rich content local", async () => {
  const [html, css] = await Promise.all([
    readFile(new URL("./sidepanel.html", import.meta.url), "utf8"),
    readFile(new URL("./sidepanel.css", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(html, /brand-mark|signal-rule|connection-status/);
  assert.match(css, /color-scheme:\s*light/);
  assert.match(css, /html,\s*body\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.workspace-shell\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.action-chips\s*\{[^}]*flex-wrap:\s*wrap/s);
  assert.doesNotMatch(css, /\.action-chips\s*\{[^}]*overflow-x:\s*(?:auto|scroll)/s);
  assert.match(css, /\.markdown-content\s+table\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /\.markdown-content\s+pre\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /\.markdown-content\s+code\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /:focus-visible/);
});

test("Side Panel keeps lifecycle reloads, loading state, message limit, and auto-scroll", async () => {
  const source = await readFile(new URL("./sidepanel.js", import.meta.url), "utf8");
  const limited = await renderState(workspace({
    histories: Array.from({ length: 10 }, (_, index) => message(index)),
  }));

  assert.equal(limited.elements.messageInput.disabled, true);
  assert.equal(limited.elements.sendButton.disabled, true);
  assert.match(limited.elements.composerHint.textContent, /limit/i);
  assert.match(source, /AGENT_BRIDGE_WORKSPACE_UPDATED/);
  assert.match(source, /AGENT_BRIDGE_WORKSPACE_RESET/);
  assert.match(source, /chrome\.tabs\.onActivated\.addListener/);
  assert.match(source, /chrome\.tabs\.onActivated\.removeListener/);
  assert.match(source, /chrome\.runtime\.onMessage\.removeListener/);
  assert.match(source, /scrollTop\s*=\s*elements\.timeline\.scrollHeight/);
  assert.match(source, /import\s*\{\s*renderMarkdown\s*\}\s*from\s*"\.\/markdown\.js"/);
});
