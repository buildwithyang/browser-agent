import { test } from "node:test";
import assert from "node:assert/strict";

import * as controller from "./workspace-controller.js";
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
function gatewayResponse({ status = 200, body = {}, protocol = "2", jsonError = null } = {}) {
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

test("Workspace seed refreshes page metadata while preserving canonical conversation", () => {
  const existing = {
    resourceUrl: "https://x/job/1",
    pageTitle: "Old title",
    quickInsight: { title: "Old insight" },
    actions: [{ id: "analyze", title: "Old analyze" }],
    selectedActionId: "tailor_resume",
    histories: [{ role: "assistant", content: "Keep me" }],
    artifacts: { cv: null, cover_letter: null },
  };
  const next = mergeWorkspaceSeed(existing, {
    resourceUrl: "https://x/job/1",
    pageTitle: "Fresh title",
    quickInsight: { title: "Fresh insight" },
    actions: [
      { id: "analyze", title: "Analyze" },
      { id: "tailor_resume", title: "Tailor resume" },
    ],
    defaultActionId: "analyze",
  });

  assert.equal(next.pageTitle, "Fresh title");
  assert.equal(next.quickInsight.title, "Fresh insight");
  assert.equal(next.selectedActionId, "tailor_resume");
  assert.deepEqual(next.histories, existing.histories);
  assert.deepEqual(next.artifacts, existing.artifacts);
  assert.equal("currentDocument" in next, false);
  assert.equal("pageText" in next, false);
  assert.equal("selectedText" in next, false);
});

test("explicit Quick Insight Action overrides an existing selected Action", () => {
  const next = mergeWorkspaceSeed(
    {
      resourceUrl: "https://x/job/1",
      actions: [
        { id: "analyze", title: "Analyze" },
        { id: "write_cover_letter", title: "Write cover letter" },
      ],
      selectedActionId: "analyze",
      histories: [{ role: "assistant", content: "Keep me" }],
    },
    {
      resourceUrl: "https://x/job/1",
      actions: [
        { id: "analyze", title: "Analyze" },
        { id: "write_cover_letter", title: "Write cover letter" },
      ],
      actionId: "write_cover_letter",
      defaultActionId: "analyze",
    }
  );

  assert.equal(next.selectedActionId, "write_cover_letter");
  assert.equal(next.histories.length, 1);
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

test("owner-scoped load migrates v1 only after v2 write, re-read, and mapping update", async () => {
  const loadOwnerScopedWorkspace = requiredExport("loadOwnerScopedWorkspace");
  const mappingKey = activeWorkspaceKey(8);
  const v1Key = "agent-bridge:workspace:v1:user-a:https%3A%2F%2Fx%2Fjob%2F1";
  const validLegacyMessage = {
    id: "30000000-0000-4000-8000-000000000001",
    role: "assistant",
    content: "Keep **opaque Markdown**",
    action_id: "analyze",
    created_at: "2026-07-20T10:00:00Z",
  };
  const oldMapping = {
    ownerId: "user-a",
    storageKey: v1Key,
    resourceUrl: "https://x/job/1",
    lang: "en",
  };
  const sessionStore = fakeStorageArea({ [mappingKey]: oldMapping });
  const workspaceStore = fakeStorageArea({
    [v1Key]: {
      resourceUrl: "https://x/job/1",
      pageTitle: "Job",
      quickInsight: { title: "Insight" },
      actions: [{ id: "analyze", title: "Analyze" }],
      selectedActionId: "analyze",
      histories: [validLegacyMessage, { role: "assistant", content: "drop invalid" }],
      currentDocument: { kind: "resume", text: "do not migrate" },
      updatedAt: "2026-07-19T00:00:00Z",
    },
  });

  const active = await loadOwnerScopedWorkspace(8, {
    ownerId: "user-a",
    sessionStore,
    workspaceStore,
  });

  assert.match(active.mapping.storageKey, /^agent-bridge:workspace:v2:/);
  assert.equal(active.state.schemaVersion, 2);
  assert.deepEqual(active.state.histories, [{ ...validLegacyMessage, attachments: [] }]);
  assert.deepEqual(active.state.artifacts, { cv: null, cover_letter: null });
  assert.equal("currentDocument" in active.state, false);
  assert.deepEqual(active.state.quickInsight, { title: "Insight" });
  assert.deepEqual(active.state.actions, [{ id: "analyze", title: "Analyze" }]);
  assert.equal(active.state.selectedActionId, "analyze");
  assert.equal(workspaceStore.data[v1Key], undefined);
  assert.deepEqual(sessionStore.data[mappingKey], active.mapping);
  assert.deepEqual(workspaceStore.getCalls, [v1Key, active.mapping.storageKey]);
  assert.deepEqual(workspaceStore.removeCalls, [[v1Key]]);
});

test("failed v2 migration write preserves v1 value and old tab mapping", async () => {
  const loadOwnerScopedWorkspace = requiredExport("loadOwnerScopedWorkspace");
  const mappingKey = activeWorkspaceKey(9);
  const v1Key = "agent-bridge:workspace:v1:user-a:resource";
  const oldMapping = {
    ownerId: "user-a",
    storageKey: v1Key,
    resourceUrl: "https://x/job/1",
  };
  const oldState = {
    resourceUrl: "https://x/job/1",
    actions: [],
    histories: [],
    currentDocument: null,
  };
  const sessionStore = fakeStorageArea({ [mappingKey]: oldMapping });
  const workspaceStore = fakeStorageArea({ [v1Key]: oldState });
  workspaceStore.set = async () => {
    throw new Error("quota exceeded");
  };

  await assert.rejects(
    loadOwnerScopedWorkspace(9, {
      ownerId: "user-a",
      sessionStore,
      workspaceStore,
    }),
    /quota exceeded/
  );

  assert.deepEqual(workspaceStore.data[v1Key], oldState);
  assert.deepEqual(sessionStore.data[mappingKey], oldMapping);
  assert.deepEqual(workspaceStore.removeCalls, []);
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
  const body = { protocol_version: 2, histories: [], artifacts: {} };
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
        required_protocol_version: 2,
        update_url: updateUrl,
      },
    })),
    (error) =>
      error instanceof ExtensionUpdateRequiredError
      && error.requiredVersion === 2
      && error.updateUrl === updateUrl
      && error.status === 426
      && shouldClearToken(error.status) === false
  );
});

test("missing or unequal protocol Header rejects before a 401 can clear auth", async () => {
  const ExtensionUpdateRequiredError = requiredExport("ExtensionUpdateRequiredError");
  for (const protocol of [null, "1", "3", "invalid"]) {
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
  for (const body of [{}, { protocol_version: 1 }, { protocol_version: "2" }]) {
    await assert.rejects(
      readGatewayResponse(gatewayResponse({ body })),
      (error) =>
        error instanceof ExtensionUpdateRequiredError
        && error.requiredVersion === 2
        && error.updateUrl === DEFAULT_EXTENSION_UPDATE_URL
    );
  }
});
