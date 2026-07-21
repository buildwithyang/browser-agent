import { test } from "node:test";
import assert from "node:assert/strict";

import * as controller from "./workspace-controller.js";
import {
  createWorkspace,
  legacyWorkspaceStorageKey,
  workspaceStorageKey,
} from "./workspace.js";
import {
  EXPIRES_KEY,
  TOKEN_KEY,
  WORKSPACE_OWNER_KEY,
  shouldClearToken,
} from "./auth.js";
import * as config from "./config.js";

const { DEFAULT_EXTENSION_UPDATE_URL, EXTENSION_PROTOCOL_HEADER } = config;

const {
  GatewayHttpError,
  activeWorkspaceKey,
  initialSelectionKey,
  loadAfterPendingSeed,
  mergeWorkspaceSeed,
  readGatewayResponse,
  restoreInitialSelection,
} = controller;

/** Return one required controller export with an assertion failure if it is missing. */
function requiredExport(name) {
  assert.equal(typeof controller[name], "function", `${name} must be exported`);
  return controller[name];
}

/** Build a Chrome-storage-compatible fake with observable reads and removals. */
function fakeStorageArea(initial = {}) {
  const data = { ...initial };
  const getCalls = [];
  const removeCalls = [];
  const setCalls = [];
  return {
    data,
    getCalls,
    removeCalls,
    setCalls,
    async get(query) {
      getCalls.push(query);
      if (query === null) return { ...data };
      if (typeof query === "string") return { [query]: data[query] };
      if (Array.isArray(query)) {
        return Object.fromEntries(query.map((key) => [key, data[key]]));
      }
      return Object.assign({}, query, data);
    },
    async remove(keys) {
      const list = Array.isArray(keys) ? keys : [keys];
      removeCalls.push(list);
      list.forEach((key) => delete data[key]);
    },
    async set(values) {
      setCalls.push(values);
      Object.assign(data, values);
    },
  };
}

/** Build one Fetch Response-shaped protocol fixture. */
function gatewayResponse({ status = 200, body = {}, protocol = "4", jsonError = null } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get(name) {
        return name === EXTENSION_PROTOCOL_HEADER ? protocol : null;
      },
    },
    async json() {
      if (jsonError) throw jsonError;
      return body;
    },
  };
}

/** Create a manually resolved promise for deterministic queue tests. */
function deferred() {
  let resolve;
  const promise = new Promise((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

/** Build one valid schema-v2 Workspace with a linked Cover Letter Artifact. */
function legacyWorkspaceState(resourceUrl) {
  const artifactId = "10000000-0000-4000-8000-000000000001";
  const attachment = {
    id: "20000000-0000-4000-8000-000000000001",
    artifact_id: artifactId,
    version: 1,
    type: "cover_letter",
    title: "Cover Letter",
    content: "Dear Hiring Manager",
  };
  return {
    schemaVersion: 2,
    resourceUrl,
    pageTitle: "Legacy role",
    quickInsight: { title: "Legacy insight" },
    actions: [{ id: "write_cover_letter", title: "Write cover letter" }],
    selectedActionId: "write_cover_letter",
    histories: [{
      id: "30000000-0000-4000-8000-000000000001",
      role: "assistant",
      content: "Created the draft.",
      action_id: "write_cover_letter",
      created_at: "2026-07-20T10:00:00Z",
      attachments: [attachment],
    }],
    artifacts: {
      cv: null,
      cover_letter: {
        id: artifactId,
        type: "cover_letter",
        version: 1,
        title: "Cover Letter",
        draft: "Dear Hiring Manager",
        attachment,
      },
    },
    updatedAt: "2026-07-20T10:00:00Z",
  };
}

test("Workspace GET waits for asynchronous seed before loading session state", async () => {
  const events = [];
  const pendingSeed = Promise.resolve().then(() => events.push("seed"));
  const result = await loadAfterPendingSeed(pendingSeed, async () => {
    events.push("load");
    return "workspace";
  });
  assert.deepEqual(events, ["seed", "load"]);
  assert.equal(result, "workspace");
});

test("active stream accepts only current identity and increasing sequence", () => {
  const createActiveWorkspaceStream = requiredExport("createActiveWorkspaceStream");
  const acceptWorkspaceStreamEvent = requiredExport("acceptWorkspaceStreamEvent");
  const workspaceStreamSnapshot = requiredExport("workspaceStreamSnapshot");
  const controller = new AbortController();
  const active = createActiveWorkspaceStream({
    operationId: "50000000-0000-4000-8000-000000000001",
    tabId: 7,
    resourceUrl: "https://x/job/1",
    submittedMessage: "original composer input",
    createdAt: "2026-07-20T12:00:00Z",
    controller,
  });

  assert.equal(acceptWorkspaceStreamEvent(active, {
    type: "started",
    operation_id: active.operationId,
    sequence: 0,
    created_at: active.createdAt,
  }), true);
  assert.equal(acceptWorkspaceStreamEvent(active, {
    type: "delta",
    operation_id: active.operationId,
    sequence: 1,
    text: "first",
  }), true);
  assert.equal(acceptWorkspaceStreamEvent(active, {
    type: "delta",
    operation_id: active.operationId,
    sequence: 1,
    text: "duplicate",
  }), false);
  assert.equal(acceptWorkspaceStreamEvent(active, {
    type: "delta",
    operation_id: "50000000-0000-4000-8000-000000000002",
    sequence: 2,
    text: "wrong operation",
  }), false);

  assert.deepEqual(workspaceStreamSnapshot(active), {
    operationId: active.operationId,
    tabId: 7,
    resourceUrl: "https://x/job/1",
    sequence: 1,
    stage: null,
    markdown: "first",
    submittedMessage: "original composer input",
    createdAt: "2026-07-20T12:00:00Z",
  });
});

test("replacing or closing an active stream aborts it without deleting a newer owner", () => {
  const createActiveWorkspaceStream = requiredExport("createActiveWorkspaceStream");
  const replaceActiveWorkspaceStream = requiredExport("replaceActiveWorkspaceStream");
  const finishActiveWorkspaceStream = requiredExport("finishActiveWorkspaceStream");
  const abortWorkspaceStreams = requiredExport("abortWorkspaceStreams");
  const streams = new Map();
  const first = createActiveWorkspaceStream({
    operationId: "50000000-0000-4000-8000-000000000001",
    tabId: 7,
    resourceUrl: "https://x/job/1",
    controller: new AbortController(),
  });
  const second = createActiveWorkspaceStream({
    operationId: "50000000-0000-4000-8000-000000000002",
    tabId: 7,
    resourceUrl: "https://x/job/1",
    controller: new AbortController(),
  });

  replaceActiveWorkspaceStream(streams, "owner/resource", first);
  replaceActiveWorkspaceStream(streams, "owner/resource", second);
  assert.equal(first.controller.signal.aborted, true);
  assert.equal(first.cancelReason, "superseded");
  assert.equal(streams.get("owner/resource"), second);

  assert.equal(
    finishActiveWorkspaceStream(streams, "owner/resource", first),
    false
  );
  assert.equal(streams.get("owner/resource"), second);

  assert.equal(abortWorkspaceStreams(
    streams,
    (active) => active.tabId === 7,
    "tab_closed"
  ), 1);
  assert.equal(second.controller.signal.aborted, true);
  assert.equal(second.cancelReason, "tab_closed");
  assert.equal(streams.size, 0);
});

test("same operationId replacement is isolated by internal generation identity", () => {
  const createActiveWorkspaceStream = requiredExport("createActiveWorkspaceStream");
  const replaceActiveWorkspaceStream = requiredExport("replaceActiveWorkspaceStream");
  const isActiveWorkspaceStream = requiredExport("isActiveWorkspaceStream");
  const acceptActiveWorkspaceStreamEvent = requiredExport("acceptActiveWorkspaceStreamEvent");
  const finishActiveWorkspaceStream = requiredExport("finishActiveWorkspaceStream");
  const streams = new Map();
  const operationId = "50000000-0000-4000-8000-000000000001";
  const first = createActiveWorkspaceStream({
    operationId,
    tabId: 7,
    resourceUrl: "https://x/job/1",
    controller: new AbortController(),
  });
  const second = createActiveWorkspaceStream({
    operationId,
    tabId: 7,
    resourceUrl: "https://x/job/1",
    controller: new AbortController(),
  });

  replaceActiveWorkspaceStream(streams, "owner/resource", first);
  replaceActiveWorkspaceStream(streams, "owner/resource", second);

  assert.equal(first.generation === second.generation, false);
  assert.equal(isActiveWorkspaceStream(streams, "owner/resource", first), false);
  assert.equal(isActiveWorkspaceStream(streams, "owner/resource", second), true);
  assert.equal(acceptActiveWorkspaceStreamEvent(streams, "owner/resource", first, {
    type: "completed",
    operation_id: operationId,
    sequence: 0,
    response: { private: "stale terminal" },
  }), false);
  assert.equal(second.markdown, "");
  assert.equal(finishActiveWorkspaceStream(streams, "owner/resource", first), false);
  assert.equal(streams.get("owner/resource"), second);
});

test("Workspace seed refreshes page metadata while preserving canonical conversation", () => {
  const existing = {
    schemaVersion: 3,
    resourceUrl: "https://x/job/1",
    pageTitle: "Old title",
    quickInsight: { title: "Old insight" },
    shortcuts: [{ id: "analyze", title: "Old analyze", prompt: "Old prompt" }],
    histories: [],
    artifacts: { cv: null, cover_letter: null },
  };
  const next = mergeWorkspaceSeed(existing, {
    resourceUrl: "https://x/job/1",
    pageTitle: "Fresh title",
    quickInsight: { title: "Fresh insight" },
    shortcuts: [
      { id: "analyze", title: "Analyze", prompt: "Analyze this role." },
      { id: "tailor_resume", title: "Tailor resume", prompt: "Tailor my resume." },
    ],
  });

  assert.equal(next.pageTitle, "Fresh title");
  assert.equal(next.quickInsight.title, "Fresh insight");
  assert.deepEqual(next.shortcuts, [
    { id: "analyze", title: "Analyze", prompt: "Analyze this role." },
    { id: "tailor_resume", title: "Tailor resume", prompt: "Tailor my resume." },
  ]);
  assert.deepEqual(next.histories, existing.histories);
  assert.deepEqual(next.artifacts, existing.artifacts);
  assert.equal("currentDocument" in next, false);
  assert.equal("pageText" in next, false);
  assert.equal("selectedText" in next, false);
});

test("user B cannot load a tab mapping owned by user A", async () => {
  const loadOwnerScopedWorkspace = requiredExport("loadOwnerScopedWorkspace");
  const mappingKey = activeWorkspaceKey(7);
  const sessionStore = fakeStorageArea({
    [mappingKey]: {
      ownerId: "user-a",
      storageKey: "workspace-a",
      resourceUrl: "https://x/job/1",
    },
  });
  const workspaceStore = fakeStorageArea({
    "workspace-a": { histories: [{ role: "assistant", content: "private" }] },
  });

  const active = await loadOwnerScopedWorkspace(7, {
    ownerId: "user-b",
    sessionStore,
    workspaceStore,
  });

  assert.equal(active, null);
  assert.equal(sessionStore.data[mappingKey], undefined);
  assert.deepEqual(workspaceStore.getCalls, []);
});

test("current mapping cannot read another resource in the same owner namespace", async () => {
  const loadOwnerScopedWorkspace = requiredExport("loadOwnerScopedWorkspace");
  const mappingKey = activeWorkspaceKey(16);
  const otherKey = workspaceStorageKey("user-a", "https://x/job/2");
  const sessionStore = fakeStorageArea({
    [mappingKey]: {
      ownerId: "user-a",
      storageKey: otherKey,
      resourceUrl: "https://x/job/1",
    },
  });
  const workspaceStore = fakeStorageArea({ [otherKey]: createWorkspace({
    resourceUrl: "https://x/job/2",
  }) });

  const active = await loadOwnerScopedWorkspace(16, {
    ownerId: "user-a",
    sessionStore,
    workspaceStore,
  });

  assert.equal(active, null);
  assert.deepEqual(workspaceStore.getCalls, []);
});

test("unsupported v1 state is discarded without recursive migration", async () => {
  const loadOwnerScopedWorkspace = requiredExport("loadOwnerScopedWorkspace");
  const mappingKey = activeWorkspaceKey(10);
  const storageKey = "agent-bridge:workspace:v1:user-a:https%3A%2F%2Fx%2Fjob%2F1";
  const mapping = {
    ownerId: "user-a",
    storageKey,
    resourceUrl: "https://x/job/1",
  };
  const sessionStore = fakeStorageArea({ [mappingKey]: mapping });
  const workspaceStore = fakeStorageArea({ [storageKey]: { histories: [] } });

  const active = await loadOwnerScopedWorkspace(10, {
    ownerId: "user-a",
    sessionStore,
    workspaceStore,
  });

  assert.equal(active, null);
  assert.deepEqual(workspaceStore.getCalls, []);
  assert.deepEqual(workspaceStore.removeCalls, []);
  assert.equal(sessionStore.data[mappingKey], undefined);
});

test("owner-scoped load migrates valid v2 state to v3 and strips Action fields", async () => {
  const loadOwnerScopedWorkspace = requiredExport("loadOwnerScopedWorkspace");
  const mappingKey = activeWorkspaceKey(8);
  const v2Key = "agent-bridge:workspace:v2:user-a:https%3A%2F%2Fx%2Fjob%2F1";
  const validLegacyMessage = {
    id: "30000000-0000-4000-8000-000000000001",
    role: "user",
    content: "Keep this turn",
    action_id: "analyze",
    created_at: "2026-07-20T10:00:00Z",
    attachments: [],
  };
  const oldMapping = {
    ownerId: "user-a",
    storageKey: v2Key,
    resourceUrl: "https://x/job/1",
    lang: "en",
  };
  const sessionStore = fakeStorageArea({ [mappingKey]: oldMapping });
  const workspaceStore = fakeStorageArea({
    [v2Key]: {
      schemaVersion: 2,
      resourceUrl: "https://x/job/1",
      pageTitle: "Job",
      quickInsight: { title: "Insight" },
      actions: [{ id: "analyze", title: "Analyze" }],
      selectedActionId: "analyze",
      histories: [validLegacyMessage],
      artifacts: { cv: null, cover_letter: null },
      updatedAt: "2026-07-19T00:00:00Z",
    },
  });

  const active = await loadOwnerScopedWorkspace(8, {
    ownerId: "user-a",
    sessionStore,
    workspaceStore,
  });

  assert.match(active.mapping.storageKey, /^agent-bridge:workspace:v3:/);
  assert.equal(active.state.schemaVersion, 3);
  const { action_id: _removedActionId, ...migratedMessage } = validLegacyMessage;
  assert.deepEqual(active.state.histories, [migratedMessage]);
  assert.deepEqual(active.state.artifacts, { cv: null, cover_letter: null });
  assert.equal("currentDocument" in active.state, false);
  assert.deepEqual(active.state.quickInsight, { title: "Insight" });
  assert.deepEqual(active.state.shortcuts, []);
  assert.equal("actions" in active.state, false);
  assert.equal("selectedActionId" in active.state, false);
  assert.equal(workspaceStore.data[v2Key], undefined);
  assert.deepEqual(sessionStore.data[mappingKey], active.mapping);
  assert.deepEqual(workspaceStore.getCalls, [v2Key, active.mapping.storageKey]);
  assert.deepEqual(workspaceStore.removeCalls, [[v2Key]]);
});

test("seed discovery migrates the exact retained v2 record without a session mapping", async () => {
  const loadWorkspaceForSeed = requiredExport("loadWorkspaceForSeed");
  const resourceUrl = "https://x/job/retained";
  const ownerId = "user-a";
  const v2Key = legacyWorkspaceStorageKey(ownerId, resourceUrl);
  const v3Key = workspaceStorageKey(ownerId, resourceUrl);
  const legacy = legacyWorkspaceState(resourceUrl);
  const sessionStore = fakeStorageArea();
  const workspaceStore = fakeStorageArea({ [v2Key]: legacy });

  const active = await loadWorkspaceForSeed(18, {
    ownerId,
    resourceUrl,
    lang: "en",
    sessionStore,
    workspaceStore,
  });

  assert.equal(active.mapping.storageKey, v3Key);
  assert.equal(active.state.schemaVersion, 3);
  assert.equal(active.state.histories[0].content, "Created the draft.");
  assert.deepEqual(active.state.artifacts, legacy.artifacts);
  assert.equal(workspaceStore.data[v2Key], undefined);
  assert.deepEqual(workspaceStore.data[v3Key], active.state);
  assert.deepEqual(sessionStore.data[activeWorkspaceKey(18)], active.mapping);
});

test("seed discovery never scans or migrates another owner or resource", async () => {
  const loadWorkspaceForSeed = requiredExport("loadWorkspaceForSeed");
  const targetResource = "https://x/job/target";
  const otherOwnerKey = legacyWorkspaceStorageKey("user-b", targetResource);
  const otherResourceKey = legacyWorkspaceStorageKey("user-a", "https://x/job/other");
  const sessionStore = fakeStorageArea();
  const workspaceStore = fakeStorageArea({
    [otherOwnerKey]: legacyWorkspaceState(targetResource),
    [otherResourceKey]: legacyWorkspaceState("https://x/job/other"),
  });

  const active = await loadWorkspaceForSeed(19, {
    ownerId: "user-a",
    resourceUrl: targetResource,
    lang: "en",
    sessionStore,
    workspaceStore,
  });

  assert.equal(active, null);
  assert.deepEqual(sessionStore.data, {});
  assert.ok(workspaceStore.data[otherOwnerKey]);
  assert.ok(workspaceStore.data[otherResourceKey]);
  assert.equal(workspaceStore.getCalls.includes(null), false);
  assert.deepEqual(workspaceStore.removeCalls, []);
});

test("seed discovery preserves exact v2 state when migration persistence fails", async () => {
  const loadWorkspaceForSeed = requiredExport("loadWorkspaceForSeed");
  const resourceUrl = "https://x/job/retry";
  const ownerId = "user-a";
  const v2Key = legacyWorkspaceStorageKey(ownerId, resourceUrl);
  const legacy = legacyWorkspaceState(resourceUrl);
  const sessionStore = fakeStorageArea();
  const workspaceStore = fakeStorageArea({ [v2Key]: legacy });
  workspaceStore.set = async () => {
    throw new Error("simulated quota failure");
  };

  await assert.rejects(
    () => loadWorkspaceForSeed(20, {
      ownerId,
      resourceUrl,
      lang: "en",
      sessionStore,
      workspaceStore,
    }),
    /quota failure/
  );
  assert.deepEqual(workspaceStore.data[v2Key], legacy);
  assert.equal(sessionStore.data[activeWorkspaceKey(20)], undefined);
  assert.deepEqual(workspaceStore.removeCalls, []);
});

test("seed discovery restores an absent mapping when legacy removal fails", async () => {
  const loadWorkspaceForSeed = requiredExport("loadWorkspaceForSeed");
  const resourceUrl = "https://x/job/remove-retry";
  const ownerId = "user-a";
  const mappingKey = activeWorkspaceKey(21);
  const v2Key = legacyWorkspaceStorageKey(ownerId, resourceUrl);
  const legacy = legacyWorkspaceState(resourceUrl);
  const sessionStore = fakeStorageArea();
  const workspaceStore = fakeStorageArea({ [v2Key]: legacy });
  workspaceStore.remove = async () => {
    throw new Error("simulated legacy removal failure");
  };

  await assert.rejects(
    () => loadWorkspaceForSeed(21, {
      ownerId,
      resourceUrl,
      lang: "en",
      sessionStore,
      workspaceStore,
    }),
    /removal failure/
  );
  assert.deepEqual(workspaceStore.data[v2Key], legacy);
  assert.equal(sessionStore.data[mappingKey], undefined);
});

test("malformed v2 state is discarded rather than partially migrated", async () => {
  const loadOwnerScopedWorkspace = requiredExport("loadOwnerScopedWorkspace");
  const mappingKey = activeWorkspaceKey(9);
  const v2Key = "agent-bridge:workspace:v2:user-a:https%3A%2F%2Fx%2Fjob%2F1";
  const oldMapping = {
    ownerId: "user-a",
    storageKey: v2Key,
    resourceUrl: "https://x/job/1",
  };
  const oldState = {
    schemaVersion: 2,
    resourceUrl: "https://x/job/1",
    actions: [],
    histories: [{ role: "assistant", content: "missing required wire fields" }],
    artifacts: { cv: null, cover_letter: null },
  };
  const sessionStore = fakeStorageArea({ [mappingKey]: oldMapping });
  const workspaceStore = fakeStorageArea({ [v2Key]: oldState });

  const active = await loadOwnerScopedWorkspace(9, {
    ownerId: "user-a",
    sessionStore,
    workspaceStore,
  });

  assert.equal(active, null);
  assert.equal(workspaceStore.data[v2Key], undefined);
  assert.equal(sessionStore.data[mappingKey], undefined);
  assert.deepEqual(workspaceStore.removeCalls, [[v2Key]]);
  assert.deepEqual(sessionStore.setCalls, []);
});

test("401 cleanup removes all Workspace session namespaces but keeps local records", async () => {
  const clearAuthWorkspaceState = requiredExport("clearAuthWorkspaceState");
  const localStore = fakeStorageArea({
    [TOKEN_KEY]: "token-a",
    [EXPIRES_KEY]: "2999-01-01T00:00:00Z",
    [WORKSPACE_OWNER_KEY]: "user-a",
    "agent-bridge:workspace:v1:user-a:resource": { histories: [] },
  });
  const sessionStore = fakeStorageArea({
    [activeWorkspaceKey(1)]: { ownerId: "user-a", storageKey: "one" },
    [activeWorkspaceKey(2)]: { ownerId: "user-a", storageKey: "two" },
    [initialSelectionKey(1)]: { url: "https://x/1", selectedText: "JD 1" },
    [initialSelectionKey(2)]: { url: "https://x/2", selectedText: "JD 2" },
    unrelated: "keep",
  });

  await clearAuthWorkspaceState({
    localStore,
    sessionStore,
    authKeys: [TOKEN_KEY, EXPIRES_KEY, WORKSPACE_OWNER_KEY],
  });

  assert.equal(localStore.data[TOKEN_KEY], undefined);
  assert.equal(localStore.data[EXPIRES_KEY], undefined);
  assert.equal(localStore.data[WORKSPACE_OWNER_KEY], undefined);
  assert.deepEqual(localStore.data["agent-bridge:workspace:v1:user-a:resource"], {
    histories: [],
  });
  assert.deepEqual(sessionStore.data, { unrelated: "keep" });
});

test("completed response is discarded when the current owner changed", async () => {
  const applyForCurrentOwner = requiredExport("applyForCurrentOwner");
  const createAuthSnapshot = requiredExport("createAuthSnapshot");
  const AuthSnapshotChangedError = requiredExport("AuthSnapshotChangedError");
  const snapshotA = createAuthSnapshot("token-a", "user-a");
  const snapshotB = createAuthSnapshot("token-b", "user-b");
  let persistCalls = 0;
  let resetNotifications = 0;

  await assert.rejects(
    applyForCurrentOwner({
      snapshot: snapshotA,
      readCurrentSnapshot: async () => snapshotB,
      apply: async () => {
        persistCalls += 1;
      },
      onOwnerMismatch: async () => {
        resetNotifications += 1;
      },
    }),
    (error) => error instanceof AuthSnapshotChangedError
  );

  assert.equal(Object.isFrozen(snapshotA), true);
  assert.deepEqual(snapshotA, { token: "token-a", ownerId: "user-a" });
  assert.equal(persistCalls, 0);
  assert.equal(resetNotifications, 1);
});

test("stale user A 401 cannot clear current user B credentials or sessions", async () => {
  const clearAuthWorkspaceStateIfCurrent = requiredExport("clearAuthWorkspaceStateIfCurrent");
  const createAuthSnapshot = requiredExport("createAuthSnapshot");
  const snapshotA = createAuthSnapshot("token-a", "user-a");
  const snapshotB = createAuthSnapshot("token-b", "user-b");
  const localStore = fakeStorageArea({
    [TOKEN_KEY]: "token-b",
    [EXPIRES_KEY]: "2999-01-01T00:00:00Z",
    [WORKSPACE_OWNER_KEY]: "user-b",
  });
  const mappingKey = activeWorkspaceKey(2);
  const sessionStore = fakeStorageArea({
    [mappingKey]: { ownerId: "user-b", storageKey: "workspace-b" },
  });
  let resetNotifications = 0;

  const cleared = await clearAuthWorkspaceStateIfCurrent({
    snapshot: snapshotA,
    readCurrentSnapshot: async () => snapshotB,
    localStore,
    sessionStore,
    authKeys: [TOKEN_KEY, EXPIRES_KEY, WORKSPACE_OWNER_KEY],
    onCleared: async () => {
      resetNotifications += 1;
    },
  });

  assert.equal(cleared, false);
  assert.equal(localStore.data[TOKEN_KEY], "token-b");
  assert.equal(localStore.data[WORKSPACE_OWNER_KEY], "user-b");
  assert.deepEqual(sessionStore.data[mappingKey], {
    ownerId: "user-b",
    storageKey: "workspace-b",
  });
  assert.equal(resetNotifications, 0);
});

test("stale rotated token cannot clear credentials for the same owner", async () => {
  const clearAuthWorkspaceStateIfCurrent = requiredExport("clearAuthWorkspaceStateIfCurrent");
  const createAuthSnapshot = requiredExport("createAuthSnapshot");
  const stale = createAuthSnapshot("token-old", "user-a");
  const current = createAuthSnapshot("token-new", "user-a");
  const localStore = fakeStorageArea({
    [TOKEN_KEY]: "token-new",
    [EXPIRES_KEY]: "2999-01-01T00:00:00Z",
    [WORKSPACE_OWNER_KEY]: "user-a",
  });
  const sessionStore = fakeStorageArea({
    [activeWorkspaceKey(2)]: { ownerId: "user-a", storageKey: "workspace-a" },
  });

  const cleared = await clearAuthWorkspaceStateIfCurrent({
    snapshot: stale,
    readCurrentSnapshot: async () => current,
    localStore,
    sessionStore,
    authKeys: [TOKEN_KEY, EXPIRES_KEY, WORKSPACE_OWNER_KEY],
  });

  assert.equal(cleared, false);
  assert.equal(localStore.data[TOKEN_KEY], "token-new");
  assert.equal(sessionStore.data[activeWorkspaceKey(2)].storageKey, "workspace-a");
});

test("double OPEN for one tab is ordered and older cleanup keeps the newer pending seed", async () => {
  const createKeyedQueue = requiredExport("createKeyedQueue");
  const queue = createKeyedQueue();
  const firstGate = deferred();
  const secondGate = deferred();
  const events = [];

  const first = queue.run(7, async () => {
    events.push("first:start");
    await firstGate.promise;
    events.push("first:end");
  });
  await Promise.resolve();
  const second = queue.run(7, async () => {
    events.push("second:start");
    await secondGate.promise;
    events.push("second:end");
  });

  assert.deepEqual(events, ["first:start"]);
  firstGate.resolve();
  await first;
  await Promise.resolve();
  assert.deepEqual(events, ["first:start", "first:end", "second:start"]);
  assert.ok(queue.pending(7), "newer seed must remain pending after older completion");
  secondGate.resolve();
  await second;
  assert.equal(queue.pending(7), undefined);
});

test("same-key concurrent SEND reloads latest state while different keys run independently", async () => {
  const createKeyedQueue = requiredExport("createKeyedQueue");
  const enqueueLatestByKey = requiredExport("enqueueLatestByKey");
  const queue = createKeyedQueue();
  const firstGate = deferred();
  let latest = 0;
  const seen = [];

  const first = enqueueLatestByKey(queue, "workspace-a", async () => latest, async (state) => {
    seen.push(["a:first", state]);
    await firstGate.promise;
    latest = state + 1;
  });
  await Promise.resolve();
  const second = enqueueLatestByKey(queue, "workspace-a", async () => latest, async (state) => {
    seen.push(["a:second", state]);
    latest = state + 1;
  });
  const other = enqueueLatestByKey(queue, "workspace-b", async () => 10, async (state) => {
    seen.push(["b:first", state]);
  });

  await other;
  assert.deepEqual(seen, [["a:first", 0], ["b:first", 10]]);
  firstGate.resolve();
  await Promise.all([first, second]);
  assert.deepEqual(seen, [["a:first", 0], ["b:first", 10], ["a:second", 1]]);
  assert.equal(latest, 2);
});

test("initial selection is restored only for the same URL and an empty fresh selection", () => {
  const fresh = { url: "https://x/job/1", selectedText: "", pageText: "fresh" };
  assert.equal(
    restoreInitialSelection(fresh, {
      url: "https://x/job/1",
      selectedText: "initial JD",
    }).selectedText,
    "initial JD"
  );
  assert.equal(
    restoreInitialSelection(
      { ...fresh, selectedText: "new selection" },
      { url: fresh.url, selectedText: "initial JD" }
    ).selectedText,
    "new selection"
  );
  assert.equal(
    restoreInitialSelection(fresh, {
      url: "https://x/job/2",
      selectedText: "other JD",
    }).selectedText,
    ""
  );
});

test("session keys isolate active Workspace and initial selection by tab", () => {
  assert.notEqual(activeWorkspaceKey(3), activeWorkspaceKey(4));
  assert.notEqual(initialSelectionKey(3), initialSelectionKey(4));
});

test("Workspace prefill is read repeatedly and removed only by its matching ACK", async () => {
  const workspacePrefillKey = requiredExport("workspacePrefillKey");
  const storeWorkspacePrefill = requiredExport("storeWorkspacePrefill");
  const readWorkspacePrefill = requiredExport("readWorkspacePrefill");
  const acknowledgeWorkspacePrefill = requiredExport("acknowledgeWorkspacePrefill");
  const sessionStore = fakeStorageArea();
  const analyze = { id: "analyze", title: "Analyze", prompt: "Analyze this role." };
  const askMore = { id: "ask_more", title: "Ask More", prompt: "" };

  const analyzeDelivery = await storeWorkspacePrefill(3, analyze, sessionStore);
  const askMoreDelivery = await storeWorkspacePrefill(4, askMore, sessionStore);

  assert.notEqual(workspacePrefillKey(3), workspacePrefillKey(4));
  assert.notEqual(analyzeDelivery.token, askMoreDelivery.token);
  assert.deepEqual(await readWorkspacePrefill(3, sessionStore), analyzeDelivery);
  assert.deepEqual(await readWorkspacePrefill(3, sessionStore), analyzeDelivery);
  assert.equal(
    await acknowledgeWorkspacePrefill(3, askMoreDelivery.token, sessionStore),
    false
  );
  assert.deepEqual(await readWorkspacePrefill(3, sessionStore), analyzeDelivery);
  assert.equal(
    await acknowledgeWorkspacePrefill(3, analyzeDelivery.token, sessionStore),
    true
  );
  assert.equal(await readWorkspacePrefill(3, sessionStore), null);
  assert.deepEqual(await readWorkspacePrefill(4, sessionStore), askMoreDelivery);
  assert.equal(await acknowledgeWorkspacePrefill(4, askMoreDelivery.token, sessionStore), true);
  assert.deepEqual(sessionStore.data, {});
});

test("stale prefill ACK cannot delete a newer delivery", async () => {
  const storeWorkspacePrefill = requiredExport("storeWorkspacePrefill");
  const readWorkspacePrefill = requiredExport("readWorkspacePrefill");
  const acknowledgeWorkspacePrefill = requiredExport("acknowledgeWorkspacePrefill");
  const sessionStore = fakeStorageArea();
  const first = await storeWorkspacePrefill(
    3,
    { id: "analyze", title: "Analyze", prompt: "Analyze this role." },
    sessionStore
  );
  const second = await storeWorkspacePrefill(
    3,
    { id: "ask_more", title: "Ask More", prompt: "" },
    sessionStore
  );

  assert.notEqual(first.token, second.token);
  assert.equal(await acknowledgeWorkspacePrefill(3, first.token, sessionStore), false);
  assert.deepEqual(await readWorkspacePrefill(3, sessionStore), second);
});

test("malformed Workspace prefill is discarded after its first read", async () => {
  const workspacePrefillKey = requiredExport("workspacePrefillKey");
  const readWorkspacePrefill = requiredExport("readWorkspacePrefill");
  const sessionStore = fakeStorageArea({
    [workspacePrefillKey(3)]: { id: "analyze", title: "Analyze" },
  });

  await assert.rejects(() => readWorkspacePrefill(3, sessionStore), /delivery|exactly/i);
  assert.equal(await readWorkspacePrefill(3, sessionStore), null);
});

test("Workspace session cleanup removes pending prefills", async () => {
  const workspacePrefillKey = requiredExport("workspacePrefillKey");
  const clearWorkspaceSessionNamespace = requiredExport("clearWorkspaceSessionNamespace");
  const sessionStore = fakeStorageArea({
    [activeWorkspaceKey(3)]: { storageKey: "workspace" },
    [workspacePrefillKey(3)]: {
      token: "50000000-0000-4000-8000-000000000001",
      shortcut: { id: "ask_more", title: "Ask More", prompt: "" },
    },
    unrelated: "keep",
  });

  await clearWorkspaceSessionNamespace(sessionStore);

  assert.deepEqual(sessionStore.data, { unrelated: "keep" });
});

test("gateway non-2xx responses reject with status and detail", async () => {
  await assert.rejects(
    readGatewayResponse(gatewayResponse({
      status: 429,
      body: { detail: "Try later" },
    })),
    (error) =>
      error instanceof GatewayHttpError
      && error.status === 429
      && error.message === "Try later"
  );
});

test("gateway success returns parsed versioned JSON", async () => {
  const body = { protocol_version: 4, histories: [], artifacts: {} };
  assert.equal(
    await readGatewayResponse(gatewayResponse({ body })),
    body
  );
});

test("gateway rejects a successful response with invalid JSON", async () => {
  const response = gatewayResponse({
    jsonError: new SyntaxError("Unexpected end of JSON input"),
  });

  await assert.rejects(
    () => readGatewayResponse(response),
    /valid JSON/i
  );
});

test("protocol Header is inspected before HTTP status handling", async () => {
  const events = [];
  const response = {
    get ok() {
      events.push("ok");
      return false;
    },
    status: 401,
    headers: {
      get(name) {
        events.push(`header:${name}`);
        return null;
      },
    },
    async json() {
      events.push("json");
      return { detail: "expired" };
    },
  };

  await assert.rejects(() => readGatewayResponse(response));
  assert.deepEqual(events, [`header:${EXTENSION_PROTOCOL_HEADER}`]);
});

test("426 carries the server-required version and update destination", async () => {
  const ExtensionUpdateRequiredError = requiredExport("ExtensionUpdateRequiredError");
  const updateUrl = "https://updates.example/agent-bridge";
  await assert.rejects(
    readGatewayResponse(gatewayResponse({
      status: 426,
      body: {
        code: "extension_update_required",
        required_protocol_version: 4,
        update_url: updateUrl,
      },
    })),
    (error) =>
      error instanceof ExtensionUpdateRequiredError
      && error.requiredVersion === 4
      && error.updateUrl === updateUrl
      && error.status === 426
      && shouldClearToken(error.status) === false
  );
});

test("missing or unequal protocol Header rejects before a 401 can clear auth", async () => {
  const ExtensionUpdateRequiredError = requiredExport("ExtensionUpdateRequiredError");
  for (const protocol of [null, "1", "2", "invalid"]) {
    await assert.rejects(
      readGatewayResponse(gatewayResponse({
        status: 401,
        protocol,
        body: { detail: "expired" },
      })),
      (error) =>
        error instanceof ExtensionUpdateRequiredError
        && error.updateUrl === DEFAULT_EXTENSION_UPDATE_URL
        && shouldClearToken(error.status) === false
    );
  }
});

test("success requires an equal top-level protocol version", async () => {
  const ExtensionUpdateRequiredError = requiredExport("ExtensionUpdateRequiredError");
  for (const body of [{}, { protocol_version: 2 }, { protocol_version: "4" }]) {
    await assert.rejects(
      readGatewayResponse(gatewayResponse({ body })),
      (error) =>
        error instanceof ExtensionUpdateRequiredError
        && error.requiredVersion === 4
        && error.updateUrl === DEFAULT_EXTENSION_UPDATE_URL
    );
  }
});
