import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import * as auth from "./auth.js";
import {
  applyWorkspaceResponse,
  createWorkspace,
  workspaceStorageKey,
} from "./workspace.js";
import { activeWorkspaceKey, workspacePrefillKey } from "./workspace-controller.js";

const RESOURCE_URL = "https://example.com/jobs/1";
const ARTIFACT_ID = "10000000-0000-4000-8000-000000000001";
const ATTACHMENT_ID = "20000000-0000-4000-8000-000000000001";
const encoder = new TextEncoder();

/** Create one Chrome-event-shaped listener registry. */
function fakeEvent() {
  const listeners = [];
  return {
    listeners,
    addListener(listener) {
      listeners.push(listener);
    },
  };
}

/** Create one mutable Chrome storage area with observable canonical writes. */
function fakeStorageArea(initial = {}) {
  const data = { ...initial };
  const setCalls = [];
  const setStartedCalls = [];
  return {
    data,
    setCalls,
    setStartedCalls,
    nextSetError: null,
    nextSetGate: null,
    async get(query) {
      if (query === null) return { ...data };
      if (typeof query === "string") return { [query]: data[query] };
      if (Array.isArray(query)) {
        return Object.fromEntries(query.map((key) => [key, data[key]]));
      }
      return Object.assign({}, query, data);
    },
    async set(values) {
      setStartedCalls.push(values);
      if (this.nextSetError) {
        const error = this.nextSetError;
        this.nextSetError = null;
        throw error;
      }
      if (this.nextSetGate) {
        const gate = this.nextSetGate;
        this.nextSetGate = null;
        await gate;
      }
      setCalls.push(values);
      Object.assign(data, values);
    },
    async remove(keys) {
      for (const key of Array.isArray(keys) ? keys : [keys]) delete data[key];
    },
  };
}

/** Create one manually driven NDJSON response with configurable abort cooperation. */
function controlledStreamResponse(signal, { ignoreAbort = false } = {}) {
  let streamController = null;
  let closed = false;
  const body = new ReadableStream({
    start(controller) {
      streamController = controller;
    },
  });
  signal.addEventListener("abort", () => {
    if (ignoreAbort) return;
    if (closed) return;
    closed = true;
    streamController.error(new DOMException("Aborted", "AbortError"));
  }, { once: true });
  return {
    response: new Response(body, {
      status: 200,
      headers: {
        "Content-Type": "application/x-ndjson",
        "X-Agent-Bridge-Protocol-Version": "4",
      },
    }),
    /** Push one complete wire event into the controlled response. */
    emit(event) {
      streamController.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
    },
    /** Close the response after its terminal event. */
    close() {
      if (closed) return;
      closed = true;
      streamController.close();
    },
  };
}

/** Create one manually resolved promise for hung Chrome API behavior. */
function deferred() {
  let resolve;
  const promise = new Promise((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

/** Wait for one asynchronous Background effect without using a fixed sleep. */
async function waitFor(predicate, message) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  assert.fail(message);
}

/** Dispatch one fake runtime request to the first Background listener that claims it. */
function dispatchRuntime(runtimeEvent, message, sender = {}) {
  return new Promise((resolve, reject) => {
    for (const listener of runtimeEvent.listeners) {
      const claimed = listener(message, sender, resolve);
      if (claimed === true) return;
    }
    reject(new Error(`No runtime listener handled ${message.type}`));
  });
}

/** Return the exact schema-v2 owner/resource key used only by discard fixtures. */
function legacyWorkspaceKey(ownerId, resourceUrl) {
  return [
    "agent-bridge:workspace:v2",
    encodeURIComponent(ownerId),
    encodeURIComponent(resourceUrl),
  ].join(":");
}

/** Build a complete successful first Artifact response from the Gateway. */
function firstArtifactResponse() {
  const attachment = {
    id: ATTACHMENT_ID,
    artifact_id: ARTIFACT_ID,
    version: 1,
    type: "cover_letter",
    title: "Cover Letter",
    content: "Dear Hiring Manager",
  };
  return {
    resource_url: RESOURCE_URL,
    result_type: "create_artifact",
    histories: [
      {
        id: "30000000-0000-4000-8000-000000000001",
        role: "user",
        content: "Write a cover letter.",
        created_at: "2026-07-20T09:59:59Z",
        attachments: [],
      },
      {
        id: "30000000-0000-4000-8000-000000000002",
        role: "assistant",
        content: "Created the first draft.",
        created_at: "2026-07-20T10:00:00Z",
        attachments: [attachment],
      },
    ],
    artifacts: {
      cv: null,
      cover_letter: {
        id: ARTIFACT_ID,
        type: "cover_letter",
        version: 1,
        title: "Cover Letter",
        draft: "Dear Hiring Manager",
        attachment,
      },
    },
    meta: {
      id: "40000000-0000-4000-8000-000000000001",
      created_at: "2026-07-20T10:00:00Z",
      status: "completed",
      input_chars: 123,
      model: "test-model",
      started_at: "2026-07-20T09:59:59Z",
      finished_at: "2026-07-20T10:00:00Z",
      duration_ms: 1000,
    },
    protocol_version: 4,
  };
}

/** Build one complete reply response for testing visible Markdown deltas. */
function firstReplyResponse() {
  const response = firstArtifactResponse();
  return {
    ...response,
    result_type: "reply",
    histories: [response.histories[0], { ...response.histories[1], attachments: [] }],
    artifacts: { cv: null, cover_letter: null },
  };
}

/** Emit one legal Artifact lifecycle through its completed terminal event. */
function emitArtifactCompletion(stream, operationId, response, createdAt) {
  stream.emit({
    type: "started",
    operation_id: operationId,
    sequence: 0,
    created_at: createdAt,
  });
  stream.emit({
    type: "status",
    operation_id: operationId,
    sequence: 1,
    stage: "generating_artifact",
    artifact_type: "cover_letter",
  });
  stream.emit({
    type: "status",
    operation_id: operationId,
    sequence: 2,
    stage: "finalizing",
  });
  stream.emit({
    type: "completed",
    operation_id: operationId,
    sequence: 3,
    response,
  });
}

test("next SEND carries the complete Artifact state returned by the prior response", async () => {
  assert.equal(
    typeof auth.buildUserMessageWorkspaceBody,
    "function",
    "background must share a pure v4 SEND builder"
  );
  const state = applyWorkspaceResponse(
    createWorkspace({
      resourceUrl: RESOURCE_URL,
      shortcuts: [{
        id: "write_cover_letter",
        title: "Write cover letter",
        prompt: "Write a cover letter.",
      }],
    }),
    firstArtifactResponse()
  );

  const body = auth.buildUserMessageWorkspaceBody(
    { url: RESOURCE_URL, title: "Job", selectedText: "JD" },
    {
      resourceUrl: RESOURCE_URL,
      state,
      message: "Make it shorter",
      lang: "en",
      operationId: "50000000-0000-4000-8000-000000000001",
    }
  );

  assert.equal("trigger" in body, false);
  assert.equal("actionId" in body, false);
  assert.deepEqual(body.histories, state.histories);
  assert.deepEqual(body.artifacts, state.artifacts);
  assert.deepEqual(
    body.histories[1].attachments[0],
    body.artifacts.cover_letter.attachment
  );
  assert.equal("currentDocument" in body, false);

  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  const operationPipeline = source.slice(
    source.indexOf("function buildOperationRequest"),
    source.indexOf("function notifyWorkspaceUpdated")
  );
  assert.match(operationPipeline, /buildUserMessageWorkspaceBody/);
  assert.doesNotMatch(operationPipeline, /buildWorkspaceBody/);
  assert.match(operationPipeline, /runWorkspaceOperation/);
  assert.doesNotMatch(operationPipeline, /currentDocument/);
});

test("Background coordinates one abortable Workspace NDJSON pipeline", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  const operationPipeline = source.slice(
    source.indexOf("function buildOperationRequest"),
    source.indexOf("function notifyWorkspaceUpdated")
  );

  assert.match(source, /const activeWorkspaceStreams = new Map\(\)/);
  assert.match(operationPipeline, /crypto\.randomUUID\(\)/);
  assert.match(operationPipeline, /operationId/);
  assert.match(operationPipeline, /buildWorkspaceHeaders/);
  assert.match(operationPipeline, /readWorkspaceEventStream/);
  assert.match(operationPipeline, /AGENT_BRIDGE_WORKSPACE_STREAM/);
  assert.doesNotMatch(operationPipeline, /readGatewayResponse\(response\)/);
});

test("Background exposes active snapshots and aborts tab- or owner-stale streams", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  const workspaceGet = source.slice(
    source.indexOf("/** Serve Side Panel reads"),
    source.indexOf("/** Execute one Side Panel SEND")
  );
  const tabRemoved = source.slice(
    source.indexOf("chrome.tabs.onRemoved.addListener"),
    source.indexOf("// Render the agent result")
  );
  const ownerChange = source.slice(source.indexOf("onOwnerChange: async"));

  assert.match(workspaceGet, /pendingStream/);
  assert.match(tabRemoved, /abortWorkspaceStreams/);
  assert.match(ownerChange, /abortAllWorkspaceStreams/);
});

test("MV3 Background coordinates completion, failure, replacement, timeout, tab, and owner lifecycles", async () => {
  const storageKey = workspaceStorageKey("user-a", RESOURCE_URL);
  const initialState = createWorkspace({
    resourceUrl: RESOURCE_URL,
    shortcuts: [{
      id: "write_cover_letter",
      title: "Write cover letter",
      prompt: "Write a cover letter.",
    }],
  });
  const local = fakeStorageArea({
    authToken: "token-a",
    workspaceOwnerId: "user-a",
    [storageKey]: initialState,
  });
  const session = fakeStorageArea({
    [activeWorkspaceKey(7)]: {
      ownerId: "user-a",
      storageKey,
      resourceUrl: RESOURCE_URL,
      lang: "en",
    },
  });
  const runtimeOnMessage = fakeEvent();
  const runtimeOnMessageExternal = fakeEvent();
  const tabsOnRemoved = fakeEvent();
  const runtimeMessages = [];
  const fetchCalls = [];
  const streams = [];
  const nextStreamOptions = [];
  let collectContextCalls = 0;
  let collectContext = async () => ({
    url: RESOURCE_URL,
    title: "Job",
    selectedText: "JD",
    pageText: "Job description",
    imageText: "",
  });
  let transientLastError = null;
  let lastErrorReads = 0;
  const runtimeApi = {
    onMessage: runtimeOnMessage,
    onMessageExternal: runtimeOnMessageExternal,
    onInstalled: fakeEvent(),
    onStartup: fakeEvent(),
    sendMessage(message, callback) {
      runtimeMessages.push(message);
      transientLastError = { message: "Could not establish connection. Receiving end does not exist." };
      callback?.();
      transientLastError = null;
    },
    getPlatformInfo(callback) { callback?.({}); },
    get lastError() {
      lastErrorReads += 1;
      return transientLastError;
    },
  };

  globalThis.chrome = {
    contextMenus: {
      onClicked: fakeEvent(),
      removeAll(callback) { callback(); },
      create() {},
      update() {},
    },
    i18n: { getUILanguage: () => "en" },
    runtime: runtimeApi,
    scripting: { executeScript: async () => undefined },
    sidePanel: {
      setOptions: async () => undefined,
      open: async () => undefined,
    },
    storage: {
      local,
      session,
      sync: fakeStorageArea({ langPref: "en" }),
      onChanged: fakeEvent(),
    },
    tabs: {
      onRemoved: tabsOnRemoved,
      create() {},
      sendMessage: async () => {
        collectContextCalls += 1;
        return collectContext();
      },
    },
  };
  globalThis.fetch = async (_url, options) => {
    const stream = controlledStreamResponse(options.signal, nextStreamOptions.shift());
    streams.push(stream);
    fetchCalls.push({ options, stream });
    return stream.response;
  };
  await import(`./background.js?mv3-behavior=${Date.now()}`);

  const retainedResourceUrl = "https://example.com/jobs/retained";
  const retainedV2Key = legacyWorkspaceKey("user-a", retainedResourceUrl);
  local.data[retainedV2Key] = {
    schemaVersion: 2,
    resourceUrl: retainedResourceUrl,
    pageTitle: "Retained role",
    quickInsight: { title: "Retained insight" },
    actions: [{ id: "analyze", title: "Analyze" }],
    selectedActionId: "analyze",
    histories: [{
      id: "30000000-0000-4000-8000-000000000099",
      role: "user",
      content: "Preserve this retained turn",
      action_id: "analyze",
      created_at: "2026-07-20T10:00:00Z",
      attachments: [],
    }],
    artifacts: { cv: null, cover_letter: null },
    updatedAt: "2026-07-20T10:00:00Z",
  };
  const freshOpen = await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_OPEN_WORKSPACE",
    shortcuts: [{ id: "analyze", title: "Analyze", prompt: "Analyze this role." }],
    workspace: { resource_url: retainedResourceUrl },
    quickInsight: { title: "Fresh insight" },
    pageTitle: "Fresh retained role",
    source: retainedResourceUrl,
    lang: "en",
  }, { tab: { id: 8 } });
  const retainedV3Key = workspaceStorageKey("user-a", retainedResourceUrl);
  assert.equal(freshOpen.ok, true);
  assert.deepEqual(freshOpen.state.histories, []);
  assert.deepEqual(freshOpen.state.artifacts, { cv: null, cover_letter: null });
  assert.equal(local.data[retainedV2Key], undefined);
  assert.deepEqual(local.data[retainedV3Key].histories, []);
  assert.deepEqual(local.data[retainedV3Key].artifacts, { cv: null, cover_letter: null });
  assert.equal(session.data[activeWorkspaceKey(8)].storageKey, retainedV3Key);
  local.setCalls.length = 0;
  local.setStartedCalls.length = 0;

  const seedGate = deferred();
  local.nextSetGate = seedGate.promise;
  const shortcuts = [{ id: "analyze", title: "Analyze", prompt: "Analyze this role." }];
  const selectedOpen = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_OPEN_WORKSPACE",
    shortcut: shortcuts[0],
    shortcuts,
    workspace: { resource_url: RESOURCE_URL },
    quickInsight: { title: "Job Match" },
    pageTitle: "Job",
    source: RESOURCE_URL,
    lang: "en",
  }, { tab: { id: 7 } });
  await waitFor(() => local.setStartedCalls.length === 1, "Selected OPEN seed did not start");
  const unselectedOpen = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_OPEN_WORKSPACE",
    shortcuts,
    workspace: { resource_url: RESOURCE_URL },
    quickInsight: { title: "Job Match" },
    pageTitle: "Job",
    source: RESOURCE_URL,
    lang: "en",
  }, { tab: { id: 7 } });
  seedGate.resolve();
  assert.equal((await selectedOpen).ok, true);
  assert.equal((await unselectedOpen).ok, true);
  const reopenedWithoutSelection = await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_GET",
    tabId: 7,
  });
  assert.equal(
    reopenedWithoutSelection.prefill,
    null,
    "a later unselected OPEN must clear the older pending Shortcut"
  );

  assert.equal((await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_OPEN_WORKSPACE",
    shortcut: shortcuts[0],
    shortcuts,
    workspace: { resource_url: RESOURCE_URL },
    quickInsight: { title: "Job Match" },
    pageTitle: "Job",
    source: RESOURCE_URL,
    lang: "en",
  }, { tab: { id: 7 } })).ok, true);
  const firstDelivery = (await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_GET",
    tabId: 7,
  })).prefill;
  const repeatedDelivery = (await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_GET",
    tabId: 7,
  })).prefill;
  assert.match(firstDelivery.token, /^[0-9a-f-]{36}$/i);
  assert.deepEqual(repeatedDelivery, firstDelivery);
  assert.deepEqual(session.data[workspacePrefillKey(7)], firstDelivery);

  assert.equal((await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_OPEN_WORKSPACE",
    shortcut: shortcuts[0],
    shortcuts,
    workspace: { resource_url: RESOURCE_URL },
    quickInsight: { title: "Job Match" },
    pageTitle: "Job",
    source: RESOURCE_URL,
    lang: "en",
  }, { tab: { id: 7 } })).ok, true);
  const newerDelivery = (await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_GET",
    tabId: 7,
  })).prefill;
  assert.notEqual(newerDelivery.token, firstDelivery.token);
  const staleAck = await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_PREFILL_ACK",
    tabId: 7,
    token: firstDelivery.token,
  });
  assert.deepEqual(staleAck, { ok: true, acknowledged: false });
  assert.deepEqual(session.data[workspacePrefillKey(7)], newerDelivery);
  const currentAck = await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_PREFILL_ACK",
    tabId: 7,
    token: newerDelivery.token,
  });
  assert.deepEqual(currentAck, { ok: true, acknowledged: true });
  assert.equal(session.data[workspacePrefillKey(7)], undefined);
  local.setCalls.length = 0;
  local.setStartedCalls.length = 0;

  const send = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "  Keep my original input  ",
  });
  await waitFor(() => fetchCalls.length === 1, "Workspace fetch did not start");
  const request = JSON.parse(fetchCalls[0].options.body);
  assert.match(request.operationId, /^[0-9a-f-]{36}$/i);
  assert.equal(fetchCalls[0].options.headers.Accept, "application/x-ndjson");
  streams[0].emit({
    type: "started",
    operation_id: request.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:00:00Z",
  });
  streams[0].emit({
    type: "status",
    operation_id: request.operationId,
    sequence: 1,
    stage: "generating_reply",
  });
  streams[0].emit({
    type: "delta",
    operation_id: request.operationId,
    sequence: 2,
    text: "Draft",
  });
  await waitFor(
    () => runtimeMessages.filter((message) => message.type === "AGENT_BRIDGE_WORKSPACE_STREAM").length === 3,
    "Stream snapshots were not broadcast"
  );

  const pending = await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_GET",
    tabId: 7,
  });
  assert.equal(pending.pendingStream.operationId, request.operationId);
  assert.equal(pending.pendingStream.markdown, "Draft");
  assert.equal(pending.pendingStream.submittedMessage, "Keep my original input");
  assert.equal(local.setCalls.length, 0, "delta must remain memory-only");

  streams[0].emit({
    type: "status",
    operation_id: request.operationId,
    sequence: 3,
    stage: "finalizing",
  });
  streams[0].emit({
    type: "completed",
    operation_id: request.operationId,
    sequence: 4,
    response: firstReplyResponse(),
  });
  streams[0].close();
  const completed = await send;
  assert.equal(completed.ok, true);
  assert.equal(local.setCalls.length, 1);
  assert.equal(local.data[storageKey].histories[1].content, "Created the first draft.");
  const snapshots = runtimeMessages
    .filter((message) => message.type === "AGENT_BRIDGE_WORKSPACE_STREAM")
    .map((message) => message.snapshot);
  assert.deepEqual(
    snapshots.map((snapshot) => snapshot.markdown),
    ["", "", "Draft", "Draft", "Draft"]
  );

  const writesAfterCompletion = local.setCalls.length;
  const failedSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Failure must restore this input",
  });
  await waitFor(() => fetchCalls.length === 2, "Failed Workspace fetch did not start");
  const failedRequest = JSON.parse(fetchCalls[1].options.body);
  streams[1].emit({
    type: "started",
    operation_id: failedRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:01:00Z",
  });
  streams[1].emit({
    type: "status",
    operation_id: failedRequest.operationId,
    sequence: 1,
    stage: "generating_reply",
  });
  streams[1].emit({
    type: "delta",
    operation_id: failedRequest.operationId,
    sequence: 2,
    text: "untrusted provider response",
  });
  streams[1].emit({
    type: "failed",
    operation_id: failedRequest.operationId,
    sequence: 3,
    code: "model_error",
    message: "secret provider response and prompt",
    recoverable: true,
  });
  streams[1].close();
  const failed = await failedSend;
  assert.equal(failed.ok, false);
  assert.equal(failed.error, "Workspace generation failed. Please retry.");
  assert.doesNotMatch(failed.error, /secret|provider|prompt/i);
  assert.equal(local.setCalls.length, writesAfterCompletion);

  const replayedOperationId = "50000000-0000-4000-8000-000000000099";
  nextStreamOptions.push({ ignoreAbort: true });
  const supersededSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Old same-resource operation",
    operationId: replayedOperationId,
  });
  await waitFor(() => fetchCalls.length === 3, "Superseded Workspace fetch did not start");
  const supersededRequest = JSON.parse(fetchCalls[2].options.body);
  streams[2].emit({
    type: "started",
    operation_id: supersededRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:02:00Z",
  });
  const replacementSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "New same-resource operation",
    operationId: replayedOperationId,
  });
  await waitFor(
    () => fetchCalls[2].options.signal.aborted,
    "New operation did not abort the old same-resource request"
  );
  const superseded = await supersededSend;
  assert.equal(superseded.stale, true);
  await waitFor(() => fetchCalls.length === 4, "Replacement Workspace fetch did not start");
  const replacementRequest = JSON.parse(fetchCalls[3].options.body);
  assert.equal(supersededRequest.operationId, replayedOperationId);
  assert.equal(replacementRequest.operationId, replayedOperationId);
  emitArtifactCompletion(
    streams[3],
    replacementRequest.operationId,
    firstArtifactResponse(),
    "2026-07-20T10:02:01Z"
  );
  streams[3].close();
  const replacement = await replacementSend;
  assert.equal(replacement.ok, true);

  const writesBeforeInvalidTerminal = local.setCalls.length;
  const invalidTerminalSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Reject invalid terminal",
  });
  await waitFor(() => fetchCalls.length === 5, "Invalid-terminal fetch did not start");
  const invalidRequest = JSON.parse(fetchCalls[4].options.body);
  emitArtifactCompletion(
    streams[4],
    invalidRequest.operationId,
    { protocol_version: 4 },
    "2026-07-20T10:03:00Z"
  );
  streams[4].close();
  const invalidTerminal = await invalidTerminalSend;
  assert.equal(invalidTerminal.ok, false);
  assert.equal(invalidTerminal.error, "Workspace response was invalid. Please retry.");
  assert.equal(local.setCalls.length, writesBeforeInvalidTerminal);

  local.nextSetError = new Error("quota details must remain private");
  const rejectedApplySend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Rejected apply",
  });
  await waitFor(() => fetchCalls.length === 6, "Rejected-apply fetch did not start");
  const rejectedApplyRequest = JSON.parse(fetchCalls[5].options.body);
  emitArtifactCompletion(
    streams[5],
    rejectedApplyRequest.operationId,
    firstArtifactResponse(),
    "2026-07-20T10:04:00Z"
  );
  streams[5].close();
  const rejectedApply = await rejectedApplySend;
  assert.equal(rejectedApply.ok, false);
  assert.doesNotMatch(rejectedApply.error, /quota|private/i);
  assert.equal(local.setCalls.length, writesBeforeInvalidTerminal);

  const applyRecoverySend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Queue recovers after rejected apply",
  });
  await waitFor(() => fetchCalls.length === 7, "Apply-recovery fetch did not start");
  const applyRecoveryRequest = JSON.parse(fetchCalls[6].options.body);
  emitArtifactCompletion(
    streams[6],
    applyRecoveryRequest.operationId,
    firstArtifactResponse(),
    "2026-07-20T10:04:01Z"
  );
  streams[6].close();
  const applyRecovery = await applyRecoverySend;
  assert.equal(applyRecovery.ok, true);

  const realSetTimeout = globalThis.setTimeout;
  const realClearTimeout = globalThis.clearTimeout;
  const timeoutHandle = {};
  let workspaceTimeout = null;
  globalThis.setTimeout = (callback, delay, ...args) => {
    if (delay === 120000) {
      workspaceTimeout = callback;
      return timeoutHandle;
    }
    return realSetTimeout(callback, delay, ...args);
  };
  globalThis.clearTimeout = (handle) => (
    handle === timeoutHandle ? undefined : realClearTimeout(handle)
  );
  const writesBeforeTimeout = local.setCalls.length;
  const fetchesBeforeTimeout = fetchCalls.length;
  const contextCallsBeforeTimeout = collectContextCalls;
  const normalCollectContext = collectContext;
  const timeoutContext = deferred();
  collectContext = () => timeoutContext.promise;
  try {
    const timedOutSend = dispatchRuntime(runtimeOnMessage, {
      type: "AGENT_BRIDGE_WORKSPACE_SEND",
      tabId: 7,
      message: "Timeout must not persist",
    });
    await waitFor(
      () => collectContextCalls === contextCallsBeforeTimeout + 1,
      "Timed Workspace context collection did not start"
    );
    assert.equal(fetchCalls.length, fetchesBeforeTimeout);
    assert.equal(typeof workspaceTimeout, "function");
    workspaceTimeout();
    const timedOut = await timedOutSend;
    assert.equal(timedOut.ok, false);
    assert.equal(local.setCalls.length, writesBeforeTimeout);
    timeoutContext.resolve({
      url: RESOURCE_URL,
      title: "Late timeout context",
      selectedText: "late",
      pageText: "late",
      imageText: "",
    });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(fetchCalls.length, fetchesBeforeTimeout);
  } finally {
    collectContext = normalCollectContext;
    globalThis.setTimeout = realSetTimeout;
    globalThis.clearTimeout = realClearTimeout;
  }

  const timeoutRecoverySend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Queue recovers after pre-fetch timeout",
  });
  await waitFor(() => fetchCalls.length === 8, "Timeout recovery did not reach fetch");
  const timeoutRecoveryRequest = JSON.parse(fetchCalls[7].options.body);
  emitArtifactCompletion(
    streams[7],
    timeoutRecoveryRequest.operationId,
    firstArtifactResponse(),
    "2026-07-20T10:05:00Z"
  );
  streams[7].close();
  assert.equal((await timeoutRecoverySend).ok, true);

  const replacementContext = deferred();
  const contextCallsBeforeReplacement = collectContextCalls;
  let useHungReplacementContext = true;
  collectContext = () => {
    if (useHungReplacementContext) {
      useHungReplacementContext = false;
      return replacementContext.promise;
    }
    return normalCollectContext();
  };
  const hungContextSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Hung pre-fetch operation",
  });
  await waitFor(
    () => collectContextCalls === contextCallsBeforeReplacement + 1,
    "Hung replacement context did not start"
  );
  const replacementAfterHungSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Replacement after hung context",
  });
  const hungContextResult = await hungContextSend;
  assert.equal(hungContextResult.stale, true);
  await waitFor(() => fetchCalls.length === 9, "Replacement did not release pre-fetch queue");
  const replacementAfterHungRequest = JSON.parse(fetchCalls[8].options.body);
  emitArtifactCompletion(
    streams[8],
    replacementAfterHungRequest.operationId,
    firstArtifactResponse(),
    "2026-07-20T10:06:00Z"
  );
  streams[8].close();
  assert.equal((await replacementAfterHungSend).ok, true);
  replacementContext.resolve({
    url: RESOURCE_URL,
    title: "Late superseded context",
    selectedText: "late",
    pageText: "late",
    imageText: "",
  });
  collectContext = normalCollectContext;
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(fetchCalls.length, 9, "late old context must not start another fetch");

  const writesBeforeTabAbort = local.setCalls.length;
  const tabContext = deferred();
  const contextCallsBeforeTabAbort = collectContextCalls;
  collectContext = () => tabContext.promise;
  const abortedSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Do not persist this",
  });
  await waitFor(
    () => collectContextCalls === contextCallsBeforeTabAbort + 1,
    "Tab-aborted context collection did not start"
  );
  for (const listener of tabsOnRemoved.listeners) listener(7);
  const aborted = await abortedSend;
  assert.equal(aborted.ok, false);
  assert.equal(aborted.stale, true);
  assert.equal(fetchCalls.length, 9);
  assert.equal(local.setCalls.length, writesBeforeTabAbort);
  assert.equal(
    runtimeMessages.some(
      (message) => message.type === "AGENT_BRIDGE_WORKSPACE_ERROR"
        && message.error?.includes("private partial")
    ),
    false
  );
  tabContext.resolve({
    url: RESOURCE_URL,
    title: "Late closed-tab context",
    selectedText: "late",
    pageText: "late",
    imageText: "",
  });
  collectContext = normalCollectContext;

  session.data[activeWorkspaceKey(7)] = {
    ownerId: "user-a",
    storageKey,
    resourceUrl: RESOURCE_URL,
    lang: "en",
  };
  const tabRecoverySend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Queue recovers after tab-close pre-fetch abort",
  });
  await waitFor(() => fetchCalls.length === 10, "Tab-close recovery did not reach fetch");
  const tabRecoveryRequest = JSON.parse(fetchCalls[9].options.body);
  emitArtifactCompletion(
    streams[9],
    tabRecoveryRequest.operationId,
    firstArtifactResponse(),
    "2026-07-20T10:07:00Z"
  );
  streams[9].close();
  assert.equal((await tabRecoverySend).ok, true);

  const ownerStaleSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Old owner operation",
  });
  await waitFor(() => fetchCalls.length === 11, "Owner-stale Workspace fetch did not start");
  const canonicalWritesBeforeOwnerChange = local.setCalls.filter(
    (values) => Object.prototype.hasOwnProperty.call(values, storageKey)
  ).length;
  const authChanged = await dispatchRuntime(runtimeOnMessageExternal, {
    type: "AUTH_TOKEN",
    token: "token-b",
    userId: "user-b",
    expiresAt: "2026-07-21T10:00:00Z",
  });
  const ownerStale = await ownerStaleSend;
  assert.equal(authChanged.ok, true);
  assert.equal(fetchCalls[10].options.signal.aborted, true);
  assert.equal(ownerStale.stale, true);
  assert.equal(session.data[activeWorkspaceKey(7)], undefined);
  assert.equal(local.data.workspaceOwnerId, "user-b");
  assert.equal(local.setCalls.filter(
    (values) => Object.prototype.hasOwnProperty.call(values, storageKey)
  ).length, canonicalWritesBeforeOwnerChange);

  local.data.authToken = "token-a";
  local.data.workspaceOwnerId = "user-a";
  session.data[activeWorkspaceKey(7)] = {
    ownerId: "user-a",
    storageKey,
    resourceUrl: RESOURCE_URL,
    lang: "en",
  };
  const persistGate = deferred();
  const startedWritesBeforeCommit = local.setStartedCalls.length;
  const fetchesBeforeCommit = fetchCalls.length;
  const completedBroadcastsBeforeCommit = runtimeMessages.filter(
    (message) => message.type === "AGENT_BRIDGE_WORKSPACE_STREAM"
      && message.eventType === "completed"
  ).length;
  local.nextSetGate = persistGate.promise;
  const orderedOldResponse = firstArtifactResponse();
  orderedOldResponse.histories[1].content = "Ordered old commit";
  const committingSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Start deferred canonical commit",
  });
  await waitFor(() => fetchCalls.length === fetchesBeforeCommit + 1, "Commit fetch did not start");
  const committingIndex = fetchesBeforeCommit;
  const committingRequest = JSON.parse(fetchCalls[committingIndex].options.body);
  emitArtifactCompletion(
    streams[committingIndex],
    committingRequest.operationId,
    orderedOldResponse,
    "2026-07-20T10:08:00Z"
  );
  streams[committingIndex].close();
  await waitFor(
    () => local.setStartedCalls.length === startedWritesBeforeCommit + 1,
    "Deferred canonical commit did not start"
  );

  let oldSettled = false;
  committingSend.then(() => {
    oldSettled = true;
  });
  const orderedReplacementSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    message: "Replacement must wait for commit",
  });
  await waitFor(
    () => fetchCalls[committingIndex].options.signal.aborted,
    "Replacement did not abort the committing generation"
  );
  await new Promise((resolve) => setImmediate(resolve));
  const oldSettledBeforeCommit = oldSettled;
  const replacementFetchedBeforeCommit = fetchCalls.length > fetchesBeforeCommit + 1;
  const oldCompletedBroadcasted = runtimeMessages.filter(
    (message) => message.type === "AGENT_BRIDGE_WORKSPACE_STREAM"
      && message.eventType === "completed"
  ).length > completedBroadcastsBeforeCommit;

  persistGate.resolve();
  const committedOldResult = await committingSend;
  assert.equal(committedOldResult.stale, true);
  await waitFor(
    () => fetchCalls.length === fetchesBeforeCommit + 2,
    "Replacement did not enter after deferred commit settled"
  );
  const replacementIndex = fetchesBeforeCommit + 1;
  const orderedReplacementRequest = JSON.parse(fetchCalls[replacementIndex].options.body);
  const orderedNewResponse = firstArtifactResponse();
  orderedNewResponse.histories[1].content = "Ordered replacement wins";
  emitArtifactCompletion(
    streams[replacementIndex],
    orderedReplacementRequest.operationId,
    orderedNewResponse,
    "2026-07-20T10:08:01Z"
  );
  streams[replacementIndex].close();
  assert.equal((await orderedReplacementSend).ok, true);

  assert.equal(oldSettledBeforeCommit, false, "old operation must retain queue during commit");
  assert.equal(replacementFetchedBeforeCommit, false, "replacement must not load before commit");
  assert.equal(oldCompletedBroadcasted, false, "stale commit must not broadcast completed");
  assert.equal(
    orderedReplacementRequest.histories[1].content,
    "Ordered old commit",
    "replacement must load the ordered committed state"
  );
  assert.equal(local.data[storageKey].histories[1].content, "Ordered replacement wins");
  assert.ok(lastErrorReads > 0, "no-receiver runtime callbacks must consume chrome.runtime.lastError");
});
