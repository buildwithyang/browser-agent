import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import * as sidepanel from "./sidepanel.js";

const { workspaceView } = sidepanel;

/** Build one complete Attachment-free v2 message for Side Panel state tests. */
function message(index) {
  return {
    id: `30000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    role: index % 2 === 0 ? "user" : "assistant",
    content: index % 2 === 0 ? "question" : "answer",
    action_id: "analyze",
    created_at: "2026-07-20T10:00:00Z",
    attachments: [],
  };
}

/** Build one complete local schema-v2 Workspace with the requested message count. */
function v2Workspace(historyCount = 0, overrides = {}) {
  return {
    schemaVersion: 2,
    resourceUrl: "https://example.com/jobs/1",
    pageTitle: "Platform Engineer",
    quickInsight: null,
    actions: [],
    selectedActionId: null,
    histories: Array.from({ length: historyCount }, (_, index) => message(index)),
    artifacts: { cv: null, cover_letter: null },
    updatedAt: null,
    ...overrides,
  };
}

test("manifest declares the Side Panel entry point and release version", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("./manifest.json", import.meta.url), "utf8")
  );
  assert.ok(manifest.permissions.includes("sidePanel"));
  assert.equal(manifest.side_panel.default_path, "sidepanel.html");
  assert.equal(manifest.version, "0.2.0");
});

test("job actions stay flat and the selected action survives history", () => {
  const state = v2Workspace(2, {
    actions: [
      { id: "analyze", title: "Analyze" },
      { id: "tailor_resume", title: "Tailor resume" },
      { id: "write_cover_letter", title: "Write cover letter" },
      { id: "ask_more", title: "Ask more" },
    ],
    selectedActionId: "tailor_resume",
    currentDocument: { kind: "resume", title: "Tailored resume", text: "Draft" },
  });

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
  assert.equal(view.canSend, true);
});

test("resume documents become a fixed website preview", () => {
  const view = workspaceView({
    actions: [{ id: "tailor_resume", title: "Tailor resume" }],
    currentDocument: {
      kind: "resume",
      title: "Tailored resume",
      text: "private resume body",
      html: "<article>private resume body</article>",
    },
  }, "en");

  assert.equal(sidepanel.CV_PREVIEW_URL, "https://browser.buildwithyang.com");
  assert.equal(view.document.presentation, "resume-preview");
  assert.equal(view.document.previewUrl, sidepanel.CV_PREVIEW_URL);
});

test("cover letter documents remain inline and copyable", () => {
  const view = workspaceView({
    actions: [{ id: "write_cover_letter", title: "Write cover letter" }],
    currentDocument: {
      kind: "cover_letter",
      title: "Cover Letter",
      text: "Dear Hiring Manager",
    },
  }, "en");

  assert.equal(view.document.presentation, "inline");
  assert.equal(view.document.previewUrl, null);
  assert.equal(view.document.text, "Dear Hiring Manager");
});

test("resume preview links open safely in a new tab", async () => {
  const source = await readFile(new URL("./sidepanel.js", import.meta.url), "utf8");
  assert.match(source, /previewLink\.target\s*=\s*"_blank"/);
  assert.match(source, /previewLink\.rel\s*=\s*"noopener noreferrer"/);
});

test("view model localizes the send limit and disables further turns", () => {
  const view = workspaceView(v2Workspace(10), "zh");
  assert.equal(view.canSend, false);
  assert.match(view.limitText, /上限/);
});

test("view model enables a valid v2 Workspace below the user-message limit", () => {
  const view = workspaceView(v2Workspace(9), "en");
  assert.equal(view.canSend, true);
  assert.equal(view.limitText, "");
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
  assert.match(source, /AGENT_BRIDGE_WORKSPACE_RESET/);
  assert.match(source, /chrome\.tabs\.onActivated\.addListener/);
  assert.match(source, /chrome\.tabs\.onActivated\.removeListener/);
  assert.match(source, /chrome\.runtime\.onMessage\.removeListener/);
  assert.match(source, /type:\s*WORKSPACE_SEND,\s*tabId:\s*requestTabId/s);
});

test("Workspace reset reloads the current panel while updates can switch tabs", () => {
  assert.equal(typeof sidepanel.workspaceLifecycleTarget, "function");
  assert.equal(
    sidepanel.workspaceLifecycleTarget(
      { type: "AGENT_BRIDGE_WORKSPACE_RESET" },
      7
    ),
    7
  );
  assert.equal(
    sidepanel.workspaceLifecycleTarget(
      { type: "AGENT_BRIDGE_WORKSPACE_UPDATED", tabId: 9 },
      7
    ),
    9
  );
  assert.equal(
    sidepanel.workspaceLifecycleTarget(
      { type: "AGENT_BRIDGE_WORKSPACE_RESET", tabId: 9 },
      7
    ),
    null
  );
});

test("Side Panel keeps Actions beside the composer instead of a dropdown", async () => {
  const html = await readFile(new URL("./sidepanel.html", import.meta.url), "utf8");
  assert.match(html, /id="action-chips"/);
  assert.match(html, /id="composer"/);
  assert.doesNotMatch(html, /<select/i);
});

test("Side Panel uses a light responsive shell without industrial decoration", async () => {
  const [html, css, source] = await Promise.all([
    readFile(new URL("./sidepanel.html", import.meta.url), "utf8"),
    readFile(new URL("./sidepanel.css", import.meta.url), "utf8"),
    readFile(new URL("./sidepanel.js", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(html, /brand-mark|signal-rule/);
  assert.doesNotMatch(source, /message-index|empty-index/);
  assert.match(css, /color-scheme:\s*light/);
  assert.match(css, /grid-template-rows:\s*auto minmax\(0,\s*1fr\) auto/);
  assert.match(css, /html,\s*body\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.workspace-header h1\s*\{[^}]*-webkit-line-clamp:\s*2/s);
  assert.match(css, /\.action-chip\s*\{[^}]*border-radius:\s*999px/s);
  assert.match(css, /\.message-content\s*\{[^}]*overflow-wrap:\s*anywhere/s);
});
