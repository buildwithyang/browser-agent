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

/** Build one cumulative Background stream snapshot for the active fixture Workspace. */
function streamSnapshot(overrides = {}) {
  return {
    operationId: "00000000-0000-4000-8000-000000000001",
    tabId: 7,
    resourceUrl: RESOURCE_URL,
    sequence: 0,
    stage: "started",
    markdown: "",
    submittedMessage: "这个岗位最看重什么？",
    createdAt: "2026-07-20T10:10:00Z",
    ...overrides,
  };
}

/** Wrap one cumulative snapshot in the Side Panel runtime message contract. */
function streamMessage(eventType, overrides = {}) {
  return {
    type: "AGENT_BRIDGE_WORKSPACE_STREAM",
    eventType,
    snapshot: streamSnapshot(overrides),
  };
}

/** Build the bounded identity retained after one local SEND has settled. */
function settledLocalOperation(overrides = {}) {
  return {
    operationId: "00000000-0000-4000-8000-000000000001",
    tabId: 7,
    resourceUrl: RESOURCE_URL,
    ...overrides,
  };
}

test("submit immediately renders a transient user turn and clears the composer", async () => {
  const setup = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  setup.elements.messageInput.value = "这个岗位最看重什么？";
  const pending = deferred();
  let request = null;

  const submit = sidepanel.submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-4000-8000-000000000001",
    now: () => "2026-07-20T10:10:00Z",
    sendRuntime: (message) => {
      request = message;
      return pending.promise;
    },
  });

  assert.equal(setup.elements.messageInput.value, "");
  assert.equal(setup.model.pendingTurn?.userText, "这个岗位最看重什么？");
  assert.equal(request?.operationId, "00000000-0000-4000-8000-000000000001");
  assert.match(setup.elements.timeline.textContent, /这个岗位最看重什么/);
  assert.equal(setup.elements.timeline.querySelectorAll(".message.transient time").length, 2);
  assert.doesNotMatch(setup.elements.timeline.textContent, /\bYou\b|\bAgent\b|你：/);

  pending.resolve({ ok: true, state: workspace({ histories: [message(1)] }), lang: "zh" });
  await submit;
  assert.equal(setup.model.pendingTurn, null);
  assert.deepEqual(setup.model.state.histories.map((item) => item.content), ["answer"]);
  assert.equal(setup.elements.timeline.querySelector(".message.transient"), null);
});

test("successful SEND settlement ignores a same-operation late delta", async () => {
  const canonical = workspace({ histories: [message(1, { content: "canonical answer" })] });
  const setup = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  setup.elements.messageInput.value = "local request";
  await sidepanel.submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-4000-8000-000000000001",
    sendRuntime: async () => ({ ok: true, state: canonical, lang: "en" }),
  });

  const accepted = sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", { sequence: 1, markdown: "late delta" })
  );

  assert.equal(accepted, false);
  assert.equal(setup.model.pendingTurn, null);
  assert.deepEqual(setup.model.state.histories.map((item) => item.content), ["canonical answer"]);
  assert.doesNotMatch(setup.elements.timeline.textContent, /late delta/);
});

test("successful SEND settlement ignores same-operation completed without reload", async () => {
  const canonical = workspace({ histories: [message(1, { content: "canonical answer" })] });
  const setup = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  setup.elements.messageInput.value = "local request";
  await sidepanel.submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-4000-8000-000000000001",
    sendRuntime: async () => ({ ok: true, state: canonical, lang: "en" }),
  });
  let reloads = 0;

  const accepted = sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("completed", { sequence: 1 }),
    { reloadWorkspace: () => { reloads += 1; } }
  );

  assert.equal(accepted, false);
  assert.equal(reloads, 0);
  assert.equal(setup.model.pendingTurn, null);
});

test("settled local operation does not block a different Background operation", async () => {
  const setup = await renderState(workspace(), {
    tabId: 7,
    settledLocalOperation: settledLocalOperation(),
  });

  const accepted = sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", {
      operationId: "00000000-0000-4000-8000-000000000002",
      sequence: 1,
      markdown: "different active operation",
    })
  );

  assert.equal(accepted, true);
  assert.equal(
    setup.model.pendingTurn?.operationId,
    "00000000-0000-4000-8000-000000000002"
  );
});

test("tab resource and owner boundaries clear the settled local operation", async () => {
  const tabSetup = await renderState(workspace(), {
    tabId: 7,
    settledLocalOperation: settledLocalOperation(),
  });
  const tabRequest = deferred();
  const tabLoad = sidepanel.loadWorkspaceForTab(tabSetup.elements, tabSetup.model, 8, {
    sendRuntime: () => tabRequest.promise,
  });
  assert.equal(tabSetup.model.settledLocalOperation, null);
  tabRequest.resolve({ ok: true, state: workspace({ resourceUrl: OTHER_RESOURCE_URL }), lang: "en" });
  await tabLoad;

  const resourceSetup = await renderState(workspace(), {
    tabId: 7,
    settledLocalOperation: settledLocalOperation(),
  });
  const resourceRequest = deferred();
  const resourceLoad = sidepanel.loadWorkspaceForTab(resourceSetup.elements, resourceSetup.model, 7, {
    sendRuntime: () => resourceRequest.promise,
  });
  resourceRequest.resolve({
    ok: true,
    state: workspace({ resourceUrl: OTHER_RESOURCE_URL }),
    lang: "en",
  });
  await resourceLoad;
  assert.equal(resourceSetup.model.settledLocalOperation, null);

  const ownerSetup = await renderState(workspace(), {
    tabId: 7,
    settledLocalOperation: settledLocalOperation(),
  });
  const ownerRequest = deferred();
  const ownerLoad = sidepanel.loadWorkspaceForTab(
    ownerSetup.elements,
    ownerSetup.model,
    7,
    { sendRuntime: () => ownerRequest.promise },
    { cancelPendingSend: true, clearState: true }
  );
  assert.equal(ownerSetup.model.settledLocalOperation, null);
  ownerRequest.resolve({ ok: true, state: workspace(), lang: "en" });
  await ownerLoad;
});

test("failed and stale local settlements ignore late runtime resurrection", async () => {
  for (const response of [
    { ok: false, error: "failed" },
    { ok: false, stale: true, error: "stale" },
  ]) {
    const setup = await renderState(workspace(), {
      tabId: 7,
      selectedActionId: "analyze",
    });
    setup.elements.messageInput.value = "restore me";
    await sidepanel.submitMessage(setup.elements, setup.model, {
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
      sendRuntime: async () => response,
    });
    let reloads = 0;

    const deltaAccepted = sidepanel.handleWorkspaceStreamMessage(
      setup.elements,
      setup.model,
      streamMessage("delta", { sequence: 1, markdown: "late resurrection" })
    );
    const completedAccepted = sidepanel.handleWorkspaceStreamMessage(
      setup.elements,
      setup.model,
      streamMessage("completed", { sequence: 2 }),
      { reloadWorkspace: () => { reloads += 1; } }
    );

    assert.equal(deltaAccepted, false);
    assert.equal(completedAccepted, false);
    assert.equal(setup.model.pendingTurn?.status, "failed");
    assert.equal(setup.elements.messageInput.value, "restore me");
    assert.equal(reloads, 0);
    assert.doesNotMatch(setup.elements.timeline.textContent, /late resurrection/);
  }
});

test("normal completed-before-response ordering applies canonical state without reload", async () => {
  const setup = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const request = deferred();
  setup.elements.messageInput.value = "local request";
  const submit = sidepanel.submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-4000-8000-000000000001",
    sendRuntime: () => request.promise,
  });
  let reloads = 0;
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("completed", { sequence: 1 }),
    { reloadWorkspace: () => { reloads += 1; } }
  );
  request.resolve({
    ok: true,
    state: workspace({ histories: [message(1, { content: "canonical once" })] }),
    lang: "en",
  });
  await submit;

  assert.equal(reloads, 0);
  assert.equal(setup.model.pendingTurn, null);
  assert.deepEqual(setup.model.state.histories.map((item) => item.content), ["canonical once"]);
});

test("cumulative stream snapshots render at most once per 50 ms and reject stale identities", async () => {
  const setup = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
    pendingTurn: {
      operationId: "00000000-0000-4000-8000-000000000001",
      tabId: 7,
      resourceUrl: RESOURCE_URL,
      userText: "Question",
      createdAt: "2026-07-20T10:10:00Z",
      sequence: 0,
      stage: "started",
      markdown: "",
      status: "pending",
    },
  });
  const scheduled = [];
  const dependencies = {
    setTimeout: (callback, delay) => {
      scheduled.push({ callback, delay });
      return scheduled.length;
    },
  };

  assert.equal(typeof sidepanel.handleWorkspaceStreamMessage, "function");
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", { sequence: 1, markdown: "**First**" }),
    dependencies
  );
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", { tabId: 8, sequence: 3, markdown: "wrong tab" }),
    dependencies
  );
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", {
      resourceUrl: OTHER_RESOURCE_URL,
      sequence: 3,
      markdown: "wrong resource",
    }),
    dependencies
  );
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    { ...streamMessage("delta", { sequence: 3, markdown: "stale wrapper" }), stale: true },
    dependencies
  );
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", {
      sequence: 2,
      markdown: "**First** <script>window.__streamXss = true</script> second",
    }),
    dependencies
  );
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", { sequence: 1, markdown: "stale" }),
    dependencies
  );
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", {
      operationId: "00000000-0000-4000-8000-000000000002",
      sequence: 3,
      markdown: "wrong operation",
    }),
    dependencies
  );

  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].delay, 50);
  assert.doesNotMatch(setup.elements.timeline.textContent, /First/);
  scheduled[0].callback();
  assert.equal(setup.elements.timeline.querySelector(".message.pending strong")?.textContent, "First");
  assert.match(setup.elements.timeline.textContent, /second/);
  assert.equal(setup.dom.window.document.querySelector(".message.pending script"), null);
  assert.equal(setup.dom.window.__streamXss, undefined);
});

test("reopened pending completion reloads and replaces canonical Workspace state", async () => {
  const setup = await renderState(workspace({
    histories: [message(0, { content: "old canonical" })],
  }), {
    tabId: 7,
    pendingTurn: {
      operationId: "00000000-0000-4000-8000-000000000001",
      tabId: 7,
      resourceUrl: RESOURCE_URL,
      userText: "Recovered submission",
      createdAt: "2026-07-20T10:10:00Z",
      sequence: 2,
      stage: "generating",
      markdown: "Transient answer",
      status: "pending",
    },
  });
  const canonicalReload = deferred();
  let reloadPromise = null;
  let reloadOptions = null;
  const dependencies = {
    reloadWorkspace: (tabId, options) => {
      reloadOptions = { tabId, ...options };
      reloadPromise = sidepanel.loadWorkspaceForTab(
        setup.elements,
        setup.model,
        tabId,
        { sendRuntime: () => canonicalReload.promise },
        options
      );
      return reloadPromise;
    },
  };

  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("completed", { sequence: 3, markdown: "Transient answer" }),
    dependencies
  );

  assert.deepEqual(reloadOptions, { tabId: 7, expectedResourceUrl: RESOURCE_URL });
  assert.equal(setup.model.pendingTurn, null);
  assert.equal(setup.model.loading, true);
  canonicalReload.resolve({
    ok: true,
    state: workspace({ histories: [message(1, { content: "new canonical" })] }),
    lang: "en",
    pendingStream: null,
  });
  await reloadPromise;
  assert.deepEqual(setup.model.state.histories.map((item) => item.content), ["new canonical"]);
});

test("reopened completion reload failure preserves canonical state and surfaces retry", async () => {
  const canonical = workspace({ histories: [message(0, { content: "canonical" })] });
  const setup = await renderState(canonical, {
    tabId: 7,
    pendingTurn: {
      ...streamSnapshot({ sequence: 2 }),
      userText: "Recovered submission",
      status: "pending",
    },
  });
  const request = deferred();
  let reloadPromise = null;
  const dependencies = {
    reloadWorkspace: (tabId, options) => {
      reloadPromise = sidepanel.loadWorkspaceForTab(
        setup.elements,
        setup.model,
        tabId,
        { sendRuntime: () => request.promise },
        options
      );
      return reloadPromise;
    },
  };

  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("completed", { sequence: 3 }),
    dependencies
  );
  request.resolve({ ok: false, error: "Canonical reload failed" });
  await reloadPromise;

  assert.deepEqual(setup.model.state.histories.map((item) => item.content), ["canonical"]);
  assert.match(setup.model.error?.message || "", /reload failed/i);
});

test("GET pending reconciliation cannot clear or replace a newer runtime operation", async () => {
  for (const pendingStream of [
    null,
    streamSnapshot({
      operationId: "00000000-0000-4000-8000-000000000002",
      sequence: 4,
      markdown: "Different GET operation",
    }),
  ]) {
    const setup = await renderState(workspace(), { tabId: 7 });
    const request = deferred();
    const load = sidepanel.loadWorkspaceForTab(setup.elements, setup.model, 7, {
      sendRuntime: () => request.promise,
    });

    sidepanel.handleWorkspaceStreamMessage(
      setup.elements,
      setup.model,
      streamMessage("delta", { sequence: 1, markdown: "Newest runtime operation" })
    );
    request.resolve({ ok: true, state: workspace(), lang: "en", pendingStream });
    await load;

    assert.equal(
      setup.model.pendingTurn?.operationId,
      "00000000-0000-4000-8000-000000000001"
    );
    assert.equal(setup.model.pendingTurn?.sequence, 1);
    assert.equal(setup.model.pendingTurn?.markdown, "Newest runtime operation");
  }
});

test("GET started before runtime may still advance the adopted operation with a higher sequence", async () => {
  const setup = await renderState(workspace(), { tabId: 7 });
  const request = deferred();
  const load = sidepanel.loadWorkspaceForTab(setup.elements, setup.model, 7, {
    sendRuntime: () => request.promise,
  });
  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", { sequence: 1, markdown: "Runtime sequence one" })
  );
  request.resolve({
    ok: true,
    state: workspace(),
    lang: "en",
    pendingStream: streamSnapshot({ sequence: 2, markdown: "GET sequence two" }),
  });
  await load;

  assert.equal(setup.model.pendingTurn?.sequence, 2);
  assert.equal(setup.model.pendingTurn?.markdown, "GET sequence two");
});

test("runtime snapshot arriving before initial GET is adopted for its confirmed resource", async () => {
  const setup = await renderState(null, { tabId: 7 });
  const request = deferred();
  const load = sidepanel.loadWorkspaceForTab(setup.elements, setup.model, 7, {
    sendRuntime: () => request.promise,
  });

  const adopted = sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("delta", { sequence: 1, markdown: "Arrived before GET" })
  );
  request.resolve({ ok: true, state: workspace(), lang: "en", pendingStream: null });
  await load;

  assert.equal(adopted, true);
  assert.equal(setup.model.pendingTurn?.markdown, "Arrived before GET");
  assert.match(setup.elements.timeline.textContent, /Arrived before GET/);
});

test("failed stream restores text without changing canonical histories", async () => {
  const canonical = workspace({ histories: [message(0, { content: "canonical" })] });
  const setup = await renderState(canonical, {
    tabId: 7,
    selectedActionId: "analyze",
    pendingTurn: {
      operationId: "00000000-0000-4000-8000-000000000001",
      tabId: 7,
      resourceUrl: RESOURCE_URL,
      userText: "retry me",
      createdAt: "2026-07-20T10:10:00Z",
      sequence: 0,
      stage: "started",
      markdown: "Partial answer",
      status: "pending",
    },
  });

  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("failed", {
      sequence: 2,
      submittedMessage: "retry me",
      markdown: "Partial answer",
    })
  );

  assert.equal(setup.elements.messageInput.value, "retry me");
  assert.deepEqual(setup.model.state.histories.map((item) => item.content), ["canonical"]);
  assert.match(setup.elements.timeline.querySelector(".message.failed")?.textContent || "", /failed/i);
});

test("interrupted SEND restores the exact original input and preserves canonical state", async () => {
  const canonical = workspace({ histories: [message(0, { content: "canonical" })] });
  const setup = await renderState(canonical, {
    tabId: 7,
    selectedActionId: "analyze",
  });
  setup.elements.messageInput.value = "  preserve my spacing  ";

  await sidepanel.submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-4000-8000-000000000001",
    sendRuntime: async () => ({ ok: false, error: "Workspace request was canceled." }),
  });

  assert.equal(setup.elements.messageInput.value, "  preserve my spacing  ");
  assert.deepEqual(setup.model.state.histories.map((item) => item.content), ["canonical"]);
  assert.match(setup.elements.timeline.querySelector(".message.failed")?.textContent || "", /failed/i);
});

test("current stale SEND settlement fails its optimistic turn and restores input", async () => {
  const setup = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const request = deferred();
  setup.elements.messageInput.value = "restore stale input";
  const submit = sidepanel.submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-4000-8000-000000000001",
    sendRuntime: () => request.promise,
  });

  request.resolve({ ok: false, stale: true, error: "The operation was superseded." });
  await submit;

  assert.equal(setup.elements.messageInput.value, "restore stale input");
  assert.equal(setup.model.pendingTurn?.status, "failed");
  assert.deepEqual(setup.model.state.histories, []);
});

test("old stale SEND settlement cannot fail a newer pending operation", async () => {
  const setup = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const request = deferred();
  setup.elements.messageInput.value = "old submission";
  const submit = sidepanel.submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-4000-8000-000000000001",
    sendRuntime: () => request.promise,
  });
  setup.model.pendingTurn = {
    ...setup.model.pendingTurn,
    operationId: "00000000-0000-4000-8000-000000000002",
    userText: "new submission",
  };
  setup.elements.messageInput.value = "new draft";

  request.resolve({ ok: false, stale: true, error: "Old operation became stale." });
  await submit;

  assert.equal(
    setup.model.pendingTurn?.operationId,
    "00000000-0000-4000-8000-000000000002"
  );
  assert.equal(setup.model.pendingTurn?.status, "pending");
  assert.equal(setup.elements.messageInput.value, "new draft");
});

test("late SEND failure never overwrites a draft typed after the first failure signal", async () => {
  const setup = await renderState(workspace(), {
    tabId: 7,
    selectedActionId: "analyze",
  });
  const request = deferred();
  setup.elements.messageInput.value = "original submission";
  const submit = sidepanel.submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-4000-8000-000000000001",
    sendRuntime: () => request.promise,
  });

  sidepanel.handleWorkspaceStreamMessage(
    setup.elements,
    setup.model,
    streamMessage("failed", { sequence: 1, submittedMessage: "original submission" })
  );
  setup.elements.messageInput.value = "new draft after failure";
  request.resolve({ ok: false, error: "Late failed settlement" });
  await submit;

  assert.equal(setup.elements.messageInput.value, "new draft after failure");
  assert.equal(setup.model.pendingTurn?.status, "failed");
});

test("GET restores pending transient turns and a tab boundary clears their timer", async () => {
  const setup = await renderState(null, { tabId: 7 });
  const firstRequest = deferred();
  const staleRequest = deferred();
  const secondRequest = deferred();
  const requests = [firstRequest, staleRequest, secondRequest];
  const cleared = [];
  const dependencies = {
    clearTimeout: (timer) => cleared.push(timer),
    sendRuntime: () => requests.shift().promise,
  };

  const firstLoad = sidepanel.loadWorkspaceForTab(setup.elements, setup.model, 7, dependencies);
  firstRequest.resolve({
    ok: true,
    state: workspace(),
    lang: "en",
    pendingStream: streamSnapshot({ submittedMessage: "Recovered draft", sequence: 3 }),
  });
  await firstLoad;
  assert.equal(setup.model.pendingTurn?.userText, "Recovered draft");
  assert.match(setup.elements.timeline.textContent, /Recovered draft/);

  setup.model.pendingTurn.sequence = 4;
  setup.model.pendingTurn.markdown = "Newest cumulative Markdown";
  const staleLoad = sidepanel.loadWorkspaceForTab(setup.elements, setup.model, 7, dependencies);
  staleRequest.resolve({
    ok: true,
    state: workspace(),
    lang: "en",
    pendingStream: streamSnapshot({ sequence: 2, markdown: "Older Markdown" }),
  });
  await staleLoad;
  assert.equal(setup.model.pendingTurn?.sequence, 4);
  assert.equal(setup.model.pendingTurn?.markdown, "Newest cumulative Markdown");

  setup.model.streamRenderTimer = 42;
  const secondLoad = sidepanel.loadWorkspaceForTab(setup.elements, setup.model, 8, dependencies);
  assert.equal(setup.model.pendingTurn, null);
  assert.deepEqual(cleared, [42]);
  secondRequest.resolve({ ok: true, state: workspace({ resourceUrl: OTHER_RESOURCE_URL }), lang: "en" });
  await secondLoad;
});

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

test("timeline distinguishes connected empty, disconnected, and initial loading", async () => {
  const connected = await renderState(workspace());
  const connectedNotice = connected.dom.window.document.querySelector(
    ".timeline-empty-state"
  );
  assert.equal(connectedNotice?.dataset.state, "connected-empty");
  assert.match(connectedNotice?.textContent || "", /Action/);

  const disconnected = await renderState(null);
  assert.equal(
    disconnected.dom.window.document.querySelector(".timeline-empty-state")?.dataset.state,
    "disconnected"
  );

  const loading = await renderState(null, { loading: true });
  const loadingTimeline = loading.dom.window.document.querySelector(".timeline");
  assert.equal(
    loadingTimeline?.querySelector(".timeline-empty-state")?.dataset.state,
    "loading"
  );
  assert.equal(loadingTimeline?.getAttribute("aria-busy"), "true");

  for (const rendered of [connected, disconnected, loading]) {
    assert.equal(rendered.dom.window.document.querySelector(".message"), null);
  }
});

test("composer integrates textarea and send button without changing stable ids", async () => {
  const { dom } = await renderState(workspace());
  const { document } = dom.window;
  const shell = document.querySelector(".input-shell");

  assert.ok(shell);
  assert.ok(shell.querySelector("#message-input"));
  assert.ok(shell.querySelector("#send-button"));
  assert.equal(document.querySelectorAll("#message-input").length, 1);
  assert.equal(document.querySelectorAll("#send-button").length, 1);
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

test("Cover Letter Attachment stays in its Assistant Message, renders plain text, and copies source", async () => {
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
  assert.equal(
    attachmentNode.querySelector(".attachment-body")?.textContent,
    COVER_LETTER_MARKDOWN
  );
  assert.equal(attachmentNode.querySelector("h1"), null);
  assert.equal(attachmentNode.querySelector("strong"), null);
  assert.equal(attachmentNode.querySelector("script"), null);
  const copyButton = attachmentNode.querySelector(".attachment-copy");
  assert.equal(copyButton?.textContent, "Copy");
  copyButton?.click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(copied, [COVER_LETTER_MARKDOWN]);
});

test("historical Attachment versions remain visible and copy their own plain text", async () => {
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
    ["# Version one", "# Version two"]
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
    assert.equal(button?.textContent, "Copy");
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

test("Quiet Precision CSS contains horizontal overflow and keeps rich content local", async () => {
  const [html, css] = await Promise.all([
    readFile(new URL("./sidepanel.html", import.meta.url), "utf8"),
    readFile(new URL("./sidepanel.css", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(html, /brand-mark|signal-rule|connection-status/);
  assert.match(css, /color-scheme:\s*light/);
  assert.match(
    css,
    /@font-face[\s\S]*font-family:\s*["']DM Sans["'][\s\S]*fonts\/dm-sans-latin-variable\.woff2/
  );
  assert.match(css, /--brand:\s*#604bd8/i);
  assert.match(css, /--ink-soft:\s*#70727d/i);
  assert.match(css, /html,\s*body\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.workspace-shell\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.timeline-empty-state\s*\{[^}]*place-items:\s*center/s);
  assert.match(css, /\.input-shell\s*\{[^}]*position:\s*relative/s);
  assert.match(css, /#send-button\s*\{[^}]*position:\s*absolute/s);
  assert.match(
    css,
    /\.message\.assistant\s+\.message-surface\s*\{[^}]*border:\s*(?:0|none)/s
  );
  assert.match(
    css,
    /\.message\.user\s+\.message-surface\s*\{[^}]*background:\s*var\(--brand-soft\)/s
  );
  assert.match(css, /\.action-chips\s*\{[^}]*flex-wrap:\s*wrap/s);
  assert.doesNotMatch(css, /\.action-chips\s*\{[^}]*overflow-x:\s*(?:auto|scroll)/s);
  assert.match(css, /\.markdown-content\s+table\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /\.markdown-content\s+pre\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /\.markdown-content\s+code\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /\.message\.pending\s+\.stream-status/);
  assert.match(css, /--danger-line:\s*color-mix\([^;]*var\(--danger\)[^;]*var\(--line\)/s);
  assert.match(
    css,
    /\.message\.failed\s+\.message-surface\s*\{[^}]*border-left:\s*2px\s+solid\s+var\(--danger-line\)/s
  );
  assert.match(
    css,
    /\.message\.pending\s+\.stream-status::after\s*\{[^}]*var\(--ink-soft\)/s
  );
  assert.doesNotMatch(
    css,
    /\.message\.pending\s+\.stream-status::after\s*\{[^}]*rgba\(96,\s*75,\s*216/s
  );
  assert.match(css, /@keyframes\s+stream-shimmer/);
  assert.match(
    css,
    /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.message\.pending\s+\.stream-status/s
  );
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
