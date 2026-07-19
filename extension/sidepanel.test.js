import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import * as sidepanel from "./sidepanel.js";

const { workspaceView } = sidepanel;

test("manifest declares the Side Panel entry point and release version", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("./manifest.json", import.meta.url), "utf8")
  );
  assert.ok(manifest.permissions.includes("sidePanel"));
  assert.equal(manifest.side_panel.default_path, "sidepanel.html");
  assert.equal(manifest.version, "0.2.0");
});

test("job actions stay flat and the selected action survives history", () => {
  const state = {
    resourceUrl: "https://example.com/jobs/1",
    pageTitle: "Platform Engineer",
    actions: [
      { id: "analyze", title: "Analyze" },
      { id: "tailor_resume", title: "Tailor resume" },
      { id: "write_cover_letter", title: "Write cover letter" },
      { id: "ask_more", title: "Ask more" },
    ],
    selectedActionId: "tailor_resume",
    histories: [
      { role: "user", content: "Focus on architecture." },
      { role: "assistant", content: "The role values distributed systems." },
    ],
    currentDocument: { kind: "resume", title: "Tailored resume", text: "Draft" },
  };

  const view = workspaceView(state, "en");

  assert.deepEqual(view.actions.map((action) => action.id), [
    "analyze",
    "tailor_resume",
    "write_cover_letter",
    "ask_more",
  ]);
  assert.equal(view.selectedActionId, "tailor_resume");
  assert.equal(view.histories.length, 2);
  assert.equal(view.document.title, "Tailored resume");
});

test("view model localizes the send limit and disables further turns", () => {
  const histories = Array.from({ length: 10 }, (_, index) => ({
    role: index % 2 ? "assistant" : "user",
    content: index % 2 ? "answer" : "question",
  }));
  const view = workspaceView({ actions: [], histories }, "zh");
  assert.equal(view.canSend, false);
  assert.match(view.limitText, /上限/);
});

test("Side Panel resolves auto and browser language from Chrome UI locale", () => {
  assert.equal(typeof sidepanel.resolveUiLang, "function");
  assert.equal(sidepanel.resolveUiLang("zh", "en-US"), "zh");
  assert.equal(sidepanel.resolveUiLang("en", "zh-CN"), "en");
  assert.equal(sidepanel.resolveUiLang("auto", "zh-CN"), "zh");
  assert.equal(sidepanel.resolveUiLang("browser", "en-US"), "en");
});

test("Side Panel follows Workspace updates and active tabs with cleanup", async () => {
  const source = await readFile(new URL("./sidepanel.js", import.meta.url), "utf8");
  assert.match(source, /AGENT_BRIDGE_WORKSPACE_UPDATED/);
  assert.match(source, /chrome\.tabs\.onActivated\.addListener/);
  assert.match(source, /chrome\.tabs\.onActivated\.removeListener/);
  assert.match(source, /chrome\.runtime\.onMessage\.removeListener/);
  assert.match(source, /type:\s*WORKSPACE_SEND,\s*tabId:\s*requestTabId/s);
});

test("Side Panel keeps Actions beside the composer instead of a dropdown", async () => {
  const html = await readFile(new URL("./sidepanel.html", import.meta.url), "utf8");
  assert.match(html, /id="action-chips"/);
  assert.match(html, /id="composer"/);
  assert.doesNotMatch(html, /<select/i);
});
