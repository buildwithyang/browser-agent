import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  createQuickInsightOperation,
  createUserMessageOperation,
  runWorkspaceOperation,
  workspaceOperationErrorEvent,
} from "./workspace-operation.js";

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

test("executable Quick Insight Actions map to one quick_insight_action request", () => {
  const mappings = [
    ["analyze", "analyze"],
    ["tailor_resume", "tailor_resume"],
    ["write_cover_letter", "write_cover_letter"],
    ["generate_cover_letter", "write_cover_letter"],
  ];

  for (const [input, actionId] of mappings) {
    assert.deepEqual(createQuickInsightOperation(input), {
      kind: "request",
      trigger: "quick_insight_action",
      actionId,
    });
  }
});

test("unknown Quick Insight Actions are rejected before opening Workspace", () => {
  assert.throws(
    () => createQuickInsightOperation("unknown_action"),
    /Unsupported Quick Insight Action/
  );
});

test("Ask More describes an open-only operation", async () => {
  const operation = createQuickInsightOperation("ask_more");
  const queue = immediateQueue();
  let requestCalls = 0;

  const result = await runWorkspaceOperation(operation, {
    queue,
    key: "workspace-a",
    loadLatest: async () => ({ histories: [] }),
    collectPageContext: async () => ({ url: "https://x/job/1" }),
    buildRequest: () => ({}),
    executeRequest: async () => {
      requestCalls += 1;
    },
    applyResponse: () => null,
  });

  assert.deepEqual(operation, {
    kind: "open_only",
    trigger: null,
    actionId: "ask_more",
  });
  assert.equal(result, null);
  assert.equal(requestCalls, 0);
  assert.deepEqual(queue.runCalls, []);
});

test("operation reloads complete latest state inside the resource queue", async () => {
  const operation = createQuickInsightOperation("tailor_resume");
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
        trigger: command.trigger,
        histories: state.histories,
        artifacts: state.artifacts,
        selectedText: pageContext.selectedText,
      };
    },
    executeRequest: async (body) => {
      events.push("request");
      return { histories: [{ id: "server-assistant" }], artifacts: latest.artifacts, body };
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
  const operation = createUserMessageOperation("analyze", "What should I improve?");
  const queue = immediateQueue();
  let requestBody = null;

  await runWorkspaceOperation(operation, {
    queue,
    key: "workspace-a",
    loadLatest: async () => ({ histories: [], artifacts: { cv: null, cover_letter: null } }),
    collectPageContext: async () => ({ url: "https://x/job/1" }),
    buildRequest: (_pageContext, _state, command) => ({
      trigger: command.trigger,
      actionId: command.actionId,
      message: command.message,
    }),
    executeRequest: async (body) => {
      requestBody = body;
      return { histories: [] };
    },
    applyResponse: (_state, response) => response,
  });

  assert.deepEqual(operation, {
    kind: "request",
    trigger: "user_message",
    actionId: "analyze",
    message: "What should I improve?",
  });
  assert.deepEqual(requestBody, {
    trigger: "user_message",
    actionId: "analyze",
    message: "What should I improve?",
  });
});

test("Workspace errors produce stable update-required or retryable events", () => {
  const update = Object.assign(new Error("Upgrade"), {
    name: "ExtensionUpdateRequiredError",
    status: 426,
    updateUrl: "https://chromewebstore.google.com/detail/agent-bridge/id",
    requiredVersion: 3,
  });
  assert.deepEqual(workspaceOperationErrorEvent(update, 7), {
    type: "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED",
    tabId: 7,
    updateUrl: update.updateUrl,
    requiredVersion: 3,
  });

  assert.deepEqual(workspaceOperationErrorEvent(new Error("Gateway unavailable"), 7), {
    type: "AGENT_BRIDGE_WORKSPACE_ERROR",
    tabId: 7,
    error: "Gateway unavailable",
    recoverable: true,
  });
});

test("background contains one shared operation request pipeline", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /runWorkspaceOperation/);
  assert.match(source, /runQuickInsightAction/);
  assert.match(source, /createUserMessageOperation/);
  assert.equal((source.match(/taskUrl\(DEFAULT_GATEWAY, "workspace"\)/g) || []).length, 1);
});

test("production package includes the Workspace operation runtime dependency", async () => {
  const source = await readFile(new URL("./package.sh", import.meta.url), "utf8");
  assert.match(source, /^\s*workspace-operation\.js\s*$/m);
});
