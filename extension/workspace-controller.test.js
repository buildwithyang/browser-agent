import { test } from "node:test";
import assert from "node:assert/strict";

import {
  GatewayHttpError,
  activeWorkspaceKey,
  initialSelectionKey,
  loadAfterPendingSeed,
  mergeWorkspaceSeed,
  readGatewayResponse,
  restoreInitialSelection,
} from "./workspace-controller.js";

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
    currentDocument: { kind: "resume", title: "Draft", text: "Keep draft" },
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
  assert.deepEqual(next.currentDocument, existing.currentDocument);
  assert.equal("pageText" in next, false);
  assert.equal("selectedText" in next, false);
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
    readGatewayResponse({
      ok: false,
      status: 429,
      json: async () => ({ detail: "Try later" }),
    }),
    (error) =>
      error instanceof GatewayHttpError
      && error.status === 429
      && error.message === "Try later"
  );
});

test("gateway success returns parsed JSON", async () => {
  const body = { histories: [], document: null };
  assert.equal(
    await readGatewayResponse({ ok: true, status: 200, json: async () => body }),
    body
  );
});
