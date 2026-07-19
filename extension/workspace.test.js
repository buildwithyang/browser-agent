import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ANONYMOUS_WORKSPACE_OWNER,
  applyWorkspaceResponse,
  canSend,
  createWorkspace,
  workspaceStorageKey,
} from "./workspace.js";

test("workspace key has a version prefix and isolates owner and resource", () => {
  const first = workspaceStorageKey("u1", "https://x/a");
  assert.match(first, /^agent-bridge:workspace:v1:/);
  assert.notEqual(first, workspaceStorageKey("u2", "https://x/a"));
  assert.notEqual(first, workspaceStorageKey("u1", "https://x/b"));
});

test("workspace key uses the explicit anonymous owner and rejects blank resources", () => {
  assert.equal(
    workspaceStorageKey("", "https://x/a"),
    workspaceStorageKey(ANONYMOUS_WORKSPACE_OWNER, "https://x/a")
  );
  assert.throws(() => workspaceStorageKey("u1", ""), /resourceUrl/);
  assert.throws(() => workspaceStorageKey("u1", "   "), /resourceUrl/);
});

test("createWorkspace persists only the whitelisted local state fields", () => {
  const state = createWorkspace({
    resourceUrl: "https://x/a",
    pageTitle: "Page",
    quickInsight: { title: "Insight" },
    actions: [{ id: "analyze", title: "Analyze" }],
    defaultActionId: "analyze",
    histories: [{ role: "user", content: "saved" }],
    currentDocument: { kind: "note", text: "draft" },
    updatedAt: "2026-07-19T00:00:00Z",
    selectedText: "private selection",
    pageText: "private page",
    imageText: "private image text",
  });

  assert.deepEqual(state, {
    resourceUrl: "https://x/a",
    pageTitle: "Page",
    quickInsight: { title: "Insight" },
    actions: [{ id: "analyze", title: "Analyze" }],
    selectedActionId: "analyze",
    histories: [{ role: "user", content: "saved" }],
    currentDocument: { kind: "note", text: "draft" },
    updatedAt: "2026-07-19T00:00:00Z",
  });
});

test("createWorkspace preserves a valid selected action before applying defaults", () => {
  const actions = [
    { id: "analyze", title: "Analyze" },
    { id: "ask_more", title: "Ask More" },
  ];
  assert.equal(
    createWorkspace({ actions, selectedActionId: "ask_more", defaultActionId: "analyze" })
      .selectedActionId,
    "ask_more"
  );
  assert.equal(
    createWorkspace({ actions, selectedActionId: "missing", defaultActionId: "analyze" })
      .selectedActionId,
    "analyze"
  );
  assert.equal(
    createWorkspace({ actions, defaultActionId: "missing" }).selectedActionId,
    "analyze"
  );
  assert.equal(
    createWorkspace({
      actions: [actions[1], actions[0]],
      default_action_id: "analyze",
    }).selectedActionId,
    "analyze"
  );
});

test("response replaces histories and document instead of appending", () => {
  const next = applyWorkspaceResponse(
    createWorkspace({
      resourceUrl: "https://x/old",
      actions: [{ id: "analyze", title: "Analyze" }],
      histories: [{ role: "user", content: "old" }],
      currentDocument: { text: "old document" },
      updatedAt: "old",
    }),
    {
      resourceUrl: "https://x/canonical",
      selectedActionId: "analyze",
      histories: [{ role: "assistant", content: "canonical" }],
      document: null,
      updatedAt: "new",
    }
  );
  assert.deepEqual(next.histories, [{ role: "assistant", content: "canonical" }]);
  assert.equal(next.currentDocument, null);
  assert.equal(next.resourceUrl, "https://x/canonical");
  assert.equal(next.selectedActionId, "analyze");
  assert.equal(next.updatedAt, "new");
});

test("response accepts the gateway's snake_case Workspace fields", () => {
  const next = applyWorkspaceResponse(
    createWorkspace({
      resourceUrl: "https://x/old",
      actions: [{ id: "ask_more", title: "Ask More" }],
    }),
    {
      resource_url: "https://x/canonical",
      selected_action_id: "ask_more",
      histories: [],
      document: null,
      meta: { created_at: "2026-07-19T00:00:00Z" },
    }
  );
  assert.equal(next.resourceUrl, "https://x/canonical");
  assert.equal(next.selectedActionId, "ask_more");
  assert.equal(next.updatedAt, "2026-07-19T00:00:00Z");
});

/** Build a minimal wire-compatible HistoryMessage fixture. */
function history(role, content) {
  return { role, content };
}

/** Build an alternating, fully valid history collection of the requested length. */
function validHistories(length) {
  return Array.from(
    { length },
    (_, index) => history(index % 2 === 0 ? "user" : "assistant", index % 2 === 0 ? "question" : "")
  );
}

test("canSend accepts exactly the tenth valid input message", () => {
  assert.equal(canSend({ histories: validHistories(9) }), true);
  assert.equal(canSend({ histories: validHistories(10) }), false);
});

test("canSend fails closed for malformed history collections and entries", () => {
  const sparseHistories = new Array(2);
  sparseHistories[0] = history("user", "question");
  const cases = [
    "not-an-array",
    undefined,
    [undefined],
    ["not-an-object"],
    [{}],
    [{ role: "system", content: "invalid role" }],
    [{ role: "user" }],
    [{ role: "user", content: "" }],
    [{ role: "user", content: "u".repeat(10_001) }],
    [{ role: "assistant", content: 123 }],
    [{ role: "assistant", content: "a".repeat(100_001) }],
    sparseHistories,
  ];

  for (const histories of cases) {
    assert.equal(canSend({ histories }), false);
  }
  assert.equal(canSend({ histories: [history("assistant", "")] }), true);
  assert.equal(canSend({}), false);
});
