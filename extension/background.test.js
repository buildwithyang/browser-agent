import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import * as auth from "./auth.js";
import {
  applyWorkspaceResponse,
  createWorkspace,
  workspaceStorageKey,
} from "./workspace.js";
import { activeWorkspaceKey } from "./workspace-controller.js";

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
        "X-Agent-Bridge-Protocol-Version": "3",
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
    selected_action_id: "write_cover_letter",
    result_type: "create_artifact",
    histories: [{
      id: "30000000-0000-4000-8000-000000000001",
      role: "assistant",
      content: "Created the first draft.",
      action_id: "write_cover_letter",
      created_at: "2026-07-20T10:00:00Z",
      attachments: [attachment],
    }],
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
    protocol_version: 3,
  };
}

test("next SEND carries the complete Artifact state returned by the prior response", async () => {
  assert.equal(
    typeof auth.buildUserMessageWorkspaceBody,
    "function",
    "background must share a pure v2 SEND builder"
  );
  const state = applyWorkspaceResponse(
    createWorkspace({
      resourceUrl: RESOURCE_URL,
      actions: [{ id: "write_cover_letter", title: "Write cover letter" }],
      selectedActionId: "write_cover_letter",
    }),
    firstArtifactResponse()
  );

  const body = auth.buildUserMessageWorkspaceBody(
    { url: RESOURCE_URL, title: "Job", selectedText: "JD" },
    {
      resourceUrl: RESOURCE_URL,
      actionId: "write_cover_letter",
      state,
      message: "Make it shorter",
      lang: "en",
      operationId: "50000000-0000-4000-8000-000000000001",
    }
  );

  assert.equal(body.trigger, "user_message");
  assert.deepEqual(body.histories, state.histories);
  assert.deepEqual(body.artifacts, state.artifacts);
  assert.deepEqual(
    body.histories[0].attachments[0],
    body.artifacts.cover_letter.attachment
  );
  assert.equal("currentDocument" in body, false);

  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  const operationPipeline = source.slice(
    source.indexOf("function buildOperationRequest"),
    source.indexOf("function notifyWorkspaceUpdated")
  );
  assert.match(operationPipeline, /buildUserMessageWorkspaceBody/);
  assert.match(operationPipeline, /buildWorkspaceBody/);
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
    actions: [{ id: "write_cover_letter", title: "Write cover letter" }],
    selectedActionId: "write_cover_letter",
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

  const send = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    actionId: "write_cover_letter",
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
    type: "delta",
    operation_id: request.operationId,
    sequence: 1,
    text: "Draft",
  });
  await waitFor(
    () => runtimeMessages.filter((message) => message.type === "AGENT_BRIDGE_WORKSPACE_STREAM").length === 2,
    "Stream snapshots were not broadcast"
  );

  const pending = await dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_GET",
    tabId: 7,
  });
  assert.equal(pending.pendingStream.operationId, request.operationId);
  assert.equal(pending.pendingStream.markdown, "Draft");
  assert.equal(pending.pendingStream.submittedMessage, "  Keep my original input  ");
  assert.equal(local.setCalls.length, 0, "delta must remain memory-only");

  streams[0].emit({
    type: "completed",
    operation_id: request.operationId,
    sequence: 2,
    response: firstArtifactResponse(),
  });
  streams[0].close();
  const completed = await send;
  assert.equal(completed.ok, true);
  assert.equal(local.setCalls.length, 1);
  assert.equal(local.data[storageKey].histories[0].content, "Created the first draft.");
  const snapshots = runtimeMessages
    .filter((message) => message.type === "AGENT_BRIDGE_WORKSPACE_STREAM")
    .map((message) => message.snapshot);
  assert.deepEqual(snapshots.map((snapshot) => snapshot.markdown), ["", "Draft", "Draft"]);

  const writesAfterCompletion = local.setCalls.length;
  const failedSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    actionId: "write_cover_letter",
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
    type: "delta",
    operation_id: failedRequest.operationId,
    sequence: 1,
    text: "untrusted provider response",
  });
  streams[1].emit({
    type: "failed",
    operation_id: failedRequest.operationId,
    sequence: 2,
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
    actionId: "write_cover_letter",
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
    actionId: "write_cover_letter",
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
  streams[3].emit({
    type: "started",
    operation_id: replacementRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:02:01Z",
  });
  streams[3].emit({
    type: "completed",
    operation_id: replacementRequest.operationId,
    sequence: 1,
    response: firstArtifactResponse(),
  });
  streams[3].close();
  const replacement = await replacementSend;
  assert.equal(replacement.ok, true);

  const writesBeforeInvalidTerminal = local.setCalls.length;
  const invalidTerminalSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    actionId: "write_cover_letter",
    message: "Reject invalid terminal",
  });
  await waitFor(() => fetchCalls.length === 5, "Invalid-terminal fetch did not start");
  const invalidRequest = JSON.parse(fetchCalls[4].options.body);
  streams[4].emit({
    type: "started",
    operation_id: invalidRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:03:00Z",
  });
  streams[4].emit({
    type: "completed",
    operation_id: invalidRequest.operationId,
    sequence: 1,
    response: { protocol_version: 3 },
  });
  streams[4].close();
  const invalidTerminal = await invalidTerminalSend;
  assert.equal(invalidTerminal.ok, false);
  assert.equal(invalidTerminal.error, "Workspace response was invalid. Please retry.");
  assert.equal(local.setCalls.length, writesBeforeInvalidTerminal);

  local.nextSetError = new Error("quota details must remain private");
  const rejectedApplySend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    actionId: "write_cover_letter",
    message: "Rejected apply",
  });
  await waitFor(() => fetchCalls.length === 6, "Rejected-apply fetch did not start");
  const rejectedApplyRequest = JSON.parse(fetchCalls[5].options.body);
  streams[5].emit({
    type: "started",
    operation_id: rejectedApplyRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:04:00Z",
  });
  streams[5].emit({
    type: "completed",
    operation_id: rejectedApplyRequest.operationId,
    sequence: 1,
    response: firstArtifactResponse(),
  });
  streams[5].close();
  const rejectedApply = await rejectedApplySend;
  assert.equal(rejectedApply.ok, false);
  assert.doesNotMatch(rejectedApply.error, /quota|private/i);
  assert.equal(local.setCalls.length, writesBeforeInvalidTerminal);

  const applyRecoverySend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    actionId: "write_cover_letter",
    message: "Queue recovers after rejected apply",
  });
  await waitFor(() => fetchCalls.length === 7, "Apply-recovery fetch did not start");
  const applyRecoveryRequest = JSON.parse(fetchCalls[6].options.body);
  streams[6].emit({
    type: "started",
    operation_id: applyRecoveryRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:04:01Z",
  });
  streams[6].emit({
    type: "completed",
    operation_id: applyRecoveryRequest.operationId,
    sequence: 1,
    response: firstArtifactResponse(),
  });
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
      actionId: "write_cover_letter",
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
    actionId: "write_cover_letter",
    message: "Queue recovers after pre-fetch timeout",
  });
  await waitFor(() => fetchCalls.length === 8, "Timeout recovery did not reach fetch");
  const timeoutRecoveryRequest = JSON.parse(fetchCalls[7].options.body);
  streams[7].emit({
    type: "started",
    operation_id: timeoutRecoveryRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:05:00Z",
  });
  streams[7].emit({
    type: "completed",
    operation_id: timeoutRecoveryRequest.operationId,
    sequence: 1,
    response: firstArtifactResponse(),
  });
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
    actionId: "write_cover_letter",
    message: "Hung pre-fetch operation",
  });
  await waitFor(
    () => collectContextCalls === contextCallsBeforeReplacement + 1,
    "Hung replacement context did not start"
  );
  const replacementAfterHungSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    actionId: "write_cover_letter",
    message: "Replacement after hung context",
  });
  const hungContextResult = await hungContextSend;
  assert.equal(hungContextResult.stale, true);
  await waitFor(() => fetchCalls.length === 9, "Replacement did not release pre-fetch queue");
  const replacementAfterHungRequest = JSON.parse(fetchCalls[8].options.body);
  streams[8].emit({
    type: "started",
    operation_id: replacementAfterHungRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:06:00Z",
  });
  streams[8].emit({
    type: "completed",
    operation_id: replacementAfterHungRequest.operationId,
    sequence: 1,
    response: firstArtifactResponse(),
  });
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
    actionId: "write_cover_letter",
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
    actionId: "write_cover_letter",
    message: "Queue recovers after tab-close pre-fetch abort",
  });
  await waitFor(() => fetchCalls.length === 10, "Tab-close recovery did not reach fetch");
  const tabRecoveryRequest = JSON.parse(fetchCalls[9].options.body);
  streams[9].emit({
    type: "started",
    operation_id: tabRecoveryRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:07:00Z",
  });
  streams[9].emit({
    type: "completed",
    operation_id: tabRecoveryRequest.operationId,
    sequence: 1,
    response: firstArtifactResponse(),
  });
  streams[9].close();
  assert.equal((await tabRecoverySend).ok, true);

  const ownerStaleSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    actionId: "write_cover_letter",
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
  orderedOldResponse.histories[0].content = "Ordered old commit";
  const committingSend = dispatchRuntime(runtimeOnMessage, {
    type: "AGENT_BRIDGE_WORKSPACE_SEND",
    tabId: 7,
    actionId: "write_cover_letter",
    message: "Start deferred canonical commit",
  });
  await waitFor(() => fetchCalls.length === fetchesBeforeCommit + 1, "Commit fetch did not start");
  const committingIndex = fetchesBeforeCommit;
  const committingRequest = JSON.parse(fetchCalls[committingIndex].options.body);
  streams[committingIndex].emit({
    type: "started",
    operation_id: committingRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:08:00Z",
  });
  streams[committingIndex].emit({
    type: "completed",
    operation_id: committingRequest.operationId,
    sequence: 1,
    response: orderedOldResponse,
  });
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
    actionId: "write_cover_letter",
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
  orderedNewResponse.histories[0].content = "Ordered replacement wins";
  streams[replacementIndex].emit({
    type: "started",
    operation_id: orderedReplacementRequest.operationId,
    sequence: 0,
    created_at: "2026-07-20T10:08:01Z",
  });
  streams[replacementIndex].emit({
    type: "completed",
    operation_id: orderedReplacementRequest.operationId,
    sequence: 1,
    response: orderedNewResponse,
  });
  streams[replacementIndex].close();
  assert.equal((await orderedReplacementSend).ok, true);

  assert.equal(oldSettledBeforeCommit, false, "old operation must retain queue during commit");
  assert.equal(replacementFetchedBeforeCommit, false, "replacement must not load before commit");
  assert.equal(oldCompletedBroadcasted, false, "stale commit must not broadcast completed");
  assert.equal(
    orderedReplacementRequest.histories[0].content,
    "Ordered old commit",
    "replacement must load the ordered committed state"
  );
  assert.equal(local.data[storageKey].histories[0].content, "Ordered replacement wins");
  assert.ok(lastErrorReads > 0, "no-receiver runtime callbacks must consume chrome.runtime.lastError");
});
