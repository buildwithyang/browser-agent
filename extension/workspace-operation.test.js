import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  createUserMessageOperation,
  identifyWorkspaceOperation,
  runWorkspaceOperation,
  WorkspaceOperationStaleError,
  workspaceOperationErrorEvent,
} from "./workspace-operation.js";
import { createKeyedQueue } from "./workspace-controller.js";

/** Create a deterministic in-memory keyed queue for operation tests. */
function immediateQueue() {
  return {
    runCalls: [],
    async run(key, operation) {
      this.runCalls.push(key);
      return operation();
    },
  };
}

/** Create one manually resolved promise for queue cancellation tests. */
function deferred() {
  let resolve;
  const promise = new Promise((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

const OPERATION_ID = "50000000-0000-4000-8000-000000000001";

/** Identify one request operation with the UUID sent to the Gateway. */
function identifiedOperation(overrides = {}) {
  return {
    kind: "user_message",
    message: "这个岗位怎么样？",
    operationId: OPERATION_ID,
    ...overrides,
  };
}

/** Build one valid stream event with the test operation identity. */
function streamEvent(type, sequence, fields = {}) {
  return { type, operation_id: OPERATION_ID, sequence, ...fields };
}

test("stream operation broadcasts cumulative snapshots and applies only completed", async () => {
  const snapshots = [];
  const applied = [];
  const completedResponse = { histories: [{ id: "assistant" }] };

  const result = await runWorkspaceOperation(identifiedOperation(), {
    queue: immediateQueue(),
    key: "workspace-a",
    loadLatest: async () => ({ histories: [] }),
    collectPageContext: async () => ({ url: "https://x/job/1" }),
    buildRequest: (_context, _latest, operation) => ({
      operationId: operation.operationId,
    }),
    executeRequest: async function* () {
      yield streamEvent("started", 0, { created_at: "2026-07-20T12:00:00Z" });
      yield streamEvent("delta", 1, { text: "这个岗" });
      yield streamEvent("delta", 2, { text: "位" });
      yield streamEvent("completed", 3, { response: completedResponse });
    },
    onEvent: (event, snapshot) => snapshots.push({ event, snapshot }),
    applyResponse: async (_latest, response) => {
      applied.push(response);
      return response;
    },
  });

  assert.deepEqual(
    snapshots.map((item) => item.snapshot.markdown),
    ["", "这个岗", "这个岗位", "这个岗位"]
  );
  assert.deepEqual(
    snapshots.map((item) => item.snapshot.sequence),
    [0, 1, 2, 3]
  );
  assert.equal(applied.length, 1);
  assert.equal(result, completedResponse);
});

test("failed stream preserves submitted input and never applies partial output", async () => {
  const snapshots = [];
  let applyCalls = 0;

  await assert.rejects(
    runWorkspaceOperation(identifiedOperation(), {
      queue: immediateQueue(),
      key: "workspace-a",
      loadLatest: async () => ({ histories: [] }),
      collectPageContext: async () => ({ url: "https://x/job/1" }),
      buildRequest: (_context, _latest, operation) => ({
        operationId: operation.operationId,
      }),
      executeRequest: async function* () {
        yield streamEvent("started", 0, { created_at: "2026-07-20T12:00:00Z" });
        yield streamEvent("delta", 1, { text: "partial private model output" });
        yield streamEvent("failed", 2, {
          code: "model_error",
          message: "provider payload must not escape",
          recoverable: true,
        });
      },
      onEvent: (_event, snapshot) => snapshots.push(snapshot),
      applyResponse: async () => {
        applyCalls += 1;
      },
    }),
    (error) => error.name === "WorkspaceStreamFailedError"
      && error.message !== "provider payload must not escape"
  );

  assert.equal(applyCalls, 0);
  assert.equal(snapshots.at(-1).markdown, "partial private model output");
  assert.equal(identifiedOperation().message, "这个岗位怎么样？");
});

test("operation rejects a stream identity mismatch before applying completion", async () => {
  let applyCalls = 0;
  await assert.rejects(
    runWorkspaceOperation(identifiedOperation(), {
      queue: immediateQueue(),
      key: "workspace-a",
      loadLatest: async () => ({}),
      collectPageContext: async () => ({}),
      buildRequest: (_context, _latest, operation) => ({ operationId: operation.operationId }),
      executeRequest: async function* () {
        yield streamEvent("started", 0, {
          operation_id: "50000000-0000-4000-8000-000000000002",
          created_at: "2026-07-20T12:00:00Z",
        });
      },
      applyResponse: async () => {
        applyCalls += 1;
      },
    }),
    /operation/i
  );
  assert.equal(applyCalls, 0);
});

test("aborting hung page-context collection releases the keyed queue", async (context) => {
  const queue = createKeyedQueue();
  const pageContextGate = deferred();
  const controller = new AbortController();
  let secondCollected = false;
  context.after(() => pageContextGate.resolve({ url: "https://x/job/1" }));

  const first = runWorkspaceOperation(identifiedOperation(), {
    queue,
    key: "workspace-a",
    signal: controller.signal,
    loadLatest: async () => ({}),
    collectPageContext: () => pageContextGate.promise,
    buildRequest: (_pageContext, _latest, operation) => ({ operationId: operation.operationId }),
    executeRequest: async function* () {
      yield streamEvent("started", 0, { created_at: "2026-07-20T12:00:00Z" });
      yield streamEvent("completed", 1, { response: {} });
    },
    applyResponse: (_latest, response) => response,
  });
  await Promise.resolve();

  const second = runWorkspaceOperation(identifiedOperation({
    operationId: "50000000-0000-4000-8000-000000000002",
  }), {
    queue,
    key: "workspace-a",
    loadLatest: async () => ({}),
    collectPageContext: async () => {
      secondCollected = true;
      return { url: "https://x/job/1" };
    },
    buildRequest: (_pageContext, _latest, operation) => ({ operationId: operation.operationId }),
    executeRequest: async function* () {
      yield {
        ...streamEvent("started", 0, { created_at: "2026-07-20T12:00:00Z" }),
        operation_id: "50000000-0000-4000-8000-000000000002",
      };
      yield {
        ...streamEvent("completed", 1, { response: { ok: true } }),
        operation_id: "50000000-0000-4000-8000-000000000002",
      };
    },
    applyResponse: (_latest, response) => response,
  });

  const firstRejected = assert.rejects(first, /abort/i);
  controller.abort("superseded");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(secondCollected, true, "the next same-key operation must enter after abort");
  await firstRejected;
  assert.deepEqual(await second, { ok: true });
});

test("an already-aborted queued generation starts no operation boundary", async () => {
  const queue = createKeyedQueue();
  const controller = new AbortController();
  let loadCalls = 0;
  controller.abort("superseded");

  await assert.rejects(runWorkspaceOperation(identifiedOperation(), {
    queue,
    key: "workspace-a",
    signal: controller.signal,
    loadLatest: async () => {
      loadCalls += 1;
      return {};
    },
    collectPageContext: async () => ({}),
    buildRequest: (_pageContext, _latest, operation) => ({ operationId: operation.operationId }),
    executeRequest: async function* () {},
    applyResponse: () => null,
  }), /abort/i);

  assert.equal(loadCalls, 0);
});

test("operation reloads complete latest state inside the resource queue", async () => {
  const operation = identifyWorkspaceOperation(
    createUserMessageOperation("Tailor my resume."),
    OPERATION_ID
  );
  const queue = immediateQueue();
  const stale = { histories: [], artifacts: { cv: null, cover_letter: null } };
  const latest = {
    histories: [{ id: "latest-assistant", role: "assistant" }],
    artifacts: { cv: { version: 2 }, cover_letter: null },
  };
  const events = [];

  const result = await runWorkspaceOperation(operation, {
    queue,
    key: "workspace-a",
    loadLatest: async () => {
      events.push("load-latest");
      return latest;
    },
    collectPageContext: async () => {
      events.push("collect-context");
      return { url: "https://x/job/1", selectedText: "JD" };
    },
    buildRequest: (pageContext, state, command) => {
      events.push("build-request");
      assert.equal(state, latest);
      assert.notEqual(state, stale);
      return {
        operationId: command.operationId,
        trigger: command.trigger,
        histories: state.histories,
        artifacts: state.artifacts,
        selectedText: pageContext.selectedText,
      };
    },
    executeRequest: async function* (body) {
      events.push("request");
      yield streamEvent("started", 0, { created_at: "2026-07-20T12:00:00Z" });
      yield streamEvent("completed", 1, {
        response: { histories: [{ id: "server-assistant" }], artifacts: latest.artifacts, body },
      });
    },
    applyResponse: async (state, response) => {
      events.push("apply-response");
      assert.equal(state, latest);
      return response;
    },
  });

  assert.deepEqual(queue.runCalls, ["workspace-a"]);
  assert.deepEqual(events, [
    "load-latest",
    "collect-context",
    "build-request",
    "request",
    "apply-response",
  ]);
  assert.deepEqual(result.histories, [{ id: "server-assistant" }]);
  assert.deepEqual(latest.histories, [{ id: "latest-assistant", role: "assistant" }]);
  assert.deepEqual(result.body.histories, latest.histories);
  assert.deepEqual(result.body.artifacts, latest.artifacts);
});

test("composer operation uses user_message through the same executor", async () => {
  const operation = identifyWorkspaceOperation(
    createUserMessageOperation("What should I improve?"),
    OPERATION_ID
  );
  const queue = immediateQueue();
  let requestBody = null;

  await runWorkspaceOperation(operation, {
    queue,
    key: "workspace-a",
    loadLatest: async () => ({ histories: [], artifacts: { cv: null, cover_letter: null } }),
    collectPageContext: async () => ({ url: "https://x/job/1" }),
    buildRequest: (_pageContext, _state, command) => ({
      operationId: command.operationId,
      message: command.message,
    }),
    executeRequest: async function* (body) {
      requestBody = body;
      yield streamEvent("started", 0, { created_at: "2026-07-20T12:00:00Z" });
      yield streamEvent("completed", 1, { response: { histories: [] } });
    },
    applyResponse: (_state, response) => response,
  });

  assert.deepEqual(operation, {
    kind: "user_message",
    message: "What should I improve?",
    operationId: OPERATION_ID,
  });
  assert.deepEqual(requestBody, {
    operationId: OPERATION_ID,
    message: "What should I improve?",
  });
});

test("composer operation rejects an empty edited message", () => {
  assert.throws(() => createUserMessageOperation(""), /required/i);
  assert.throws(() => createUserMessageOperation("   "), /required/i);
  assert.throws(() => createUserMessageOperation({ message: "not a string" }), /required/i);
});

test("Workspace errors produce stable update-required or retryable events", () => {
  const update = Object.assign(new Error("Upgrade"), {
    name: "ExtensionUpdateRequiredError",
    status: 426,
    updateUrl: "https://chromewebstore.google.com/detail/agent-bridge/id",
    requiredVersion: 4,
  });
  assert.deepEqual(workspaceOperationErrorEvent(update, 7), {
    type: "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED",
    tabId: 7,
    updateUrl: update.updateUrl,
    requiredVersion: 4,
  });

  assert.deepEqual(workspaceOperationErrorEvent(new Error("Bearer secret private prompt"), 7), {
    type: "AGENT_BRIDGE_WORKSPACE_ERROR",
    tabId: 7,
    error: "Workspace request failed. Please retry.",
    recoverable: true,
  });
  const stale = workspaceOperationErrorEvent(new WorkspaceOperationStaleError(), 7);
  assert.equal(stale.stale, true);
  assert.doesNotMatch(stale.error, /superseded/i);
});

test("background contains one shared operation request pipeline", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /runWorkspaceOperation/);
  assert.doesNotMatch(source, /runQuickInsightAction/);
  assert.match(source, /createUserMessageOperation/);
  assert.equal((source.match(/taskUrl\(DEFAULT_GATEWAY, "workspace"\)/g) || []).length, 1);
});

test("production package includes the Workspace operation runtime dependency", async () => {
  const source = await readFile(new URL("./package.sh", import.meta.url), "utf8");
  assert.match(source, /^\s*workspace-operation\.js\s*$/m);
});
