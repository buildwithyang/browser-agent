import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { JSDOM } from "jsdom";

import * as sidepanel from "./sidepanel.js";

const RESOURCE_URL = "https://www.linkedin.com/jobs/view/123";
const COVER_LETTER_MARKDOWN = [
  "# Application",
  "",
  "Dear **Hiring Manager**",
  "",
  "<script>window.__attachmentXss = true</script>",
].join("\n");

/** Return a deterministic UUID-shaped identifier for one fixture category and index. */
function fixtureId(category, index) {
  return `${category}0000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
}

/** Build one complete protocol-v2 message fixture. */
function message(index, overrides = {}) {
  const role = overrides.role || (index % 2 === 0 ? "user" : "assistant");
  return {
    id: fixtureId("3", index + 1),
    role,
    content: role === "user" ? "question" : "answer",
    action_id: "analyze",
    created_at: `2026-07-20T10:0${index}:00Z`,
    attachments: [],
    ...overrides,
  };
}

/** Build one immutable Attachment fixture. */
function attachment({ type = "cover_letter", content = COVER_LETTER_MARKDOWN } = {}) {
  return {
    id: fixtureId("2", type === "cv" ? 2 : 1),
    artifact_id: fixtureId("1", type === "cv" ? 2 : 1),
    version: 1,
    type,
    title: type === "cv" ? "Tailored CV" : "Cover Letter",
    content,
  };
}

/** Build one valid schema-v2 Workspace with optional state overrides. */
function workspace(overrides = {}) {
  return {
    schemaVersion: 2,
    resourceUrl: RESOURCE_URL,
    pageTitle: "Platform Engineer",
    quickInsight: {
      title: "Strong match",
      cards: [{ type: "score", id: "decision", title: "Decision", score: 87 }],
    },
    actions: [
      { id: "analyze", title: "Analyze" },
      { id: "ask_more", title: "Ask More" },
    ],
    selectedActionId: "analyze",
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    updatedAt: null,
    ...overrides,
  };
}

/** Create a detached Side Panel document from the production HTML. */
async function panelDocument() {
  const html = await readFile(new URL("./sidepanel.html", import.meta.url), "utf8");
  return new JSDOM(html, { url: "https://extension.invalid/sidepanel.html" });
}

/** Render one state through the production renderer with deterministic dependencies. */
async function renderState(state, overrides = {}) {
  assert.equal(typeof sidepanel.renderSidePanel, "function");
  const dom = await panelDocument();
  const copied = [];
  const model = {
    state,
    lang: "en",
    uiLanguage: "en-US",
    selectedActionId: state?.selectedActionId || null,
    loading: false,
    error: null,
    ...overrides,
  };
  const elements = sidepanel.renderSidePanel(dom.window.document, model, {
    copyText: async (text) => copied.push(text),
  });
  return { copied, dom, elements, model };
}

test("manifest declares the Side Panel entry point and release version", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("./manifest.json", import.meta.url), "utf8")
  );
  assert.ok(manifest.permissions.includes("sidePanel"));
  assert.equal(manifest.side_panel.default_path, "sidepanel.html");
  assert.equal(manifest.version, "0.2.0");
});

test("header contains only page identity, source, and an optional match score", async () => {
  const { dom } = await renderState(workspace());
  const { document } = dom.window;
  const header = document.querySelector(".workspace-header");

  assert.equal(header?.querySelector("h1")?.textContent, "Platform Engineer");
  assert.match(header?.querySelector(".source-link")?.textContent || "", /linkedin\.com/);
  assert.equal(header?.querySelector(".match-score")?.textContent, "87 / 100");
  assert.equal(header?.querySelector(".connection-status"), null);
  assert.equal(document.querySelector(".insight-card"), null);
  assert.equal(document.querySelector(".artifact-card"), null);
  assert.equal(document.querySelector(".resume-preview-card"), null);
  assert.doesNotMatch(document.body.textContent, /Business Overview|Role Focus|Strength|Gap|Quick Insight|Latest Artifact/i);

  const withoutScore = await renderState(workspace({ quickInsight: null }));
  assert.equal(
    withoutScore.dom.window.document.querySelector(".match-score:not([hidden])"),
    null
  );
});

test("messages preserve chronology, render roles safely, and show semantic local times", async () => {
  const histories = [
    message(0, { content: "<img src=x onerror=alert(1)> first" }),
    message(1, {
      content: "## Second\n\n**safe**<script>window.__messageXss = true</script>",
    }),
  ];
  const { dom } = await renderState(workspace({ histories }));
  const { document } = dom.window;
  const rendered = [...document.querySelectorAll(".message")];

  assert.deepEqual(
    rendered.map((item) => item.querySelector(".message-content")?.textContent.trim()),
    ["<img src=x onerror=alert(1)> first", "Second\nsafe"]
  );
  assert.equal(rendered[0].querySelector("img"), null, "User content must stay text");
  assert.equal(rendered[1].querySelector("strong")?.textContent, "safe");
  assert.equal(rendered[1].querySelector("script"), null);
  assert.equal(dom.window.__messageXss, undefined);
  assert.equal(document.querySelector(".message-role"), null);
  assert.doesNotMatch(rendered.map((item) => item.textContent).join(" "), /\bYou\b|\bAgent\b|你/);

  const times = [...document.querySelectorAll(".message time")];
  assert.equal(times.length, histories.length);
  for (const [index, time] of times.entries()) {
    assert.match(time.textContent, /^\d{2}:\d{2}$/);
    assert.equal(time.getAttribute("datetime"), histories[index].created_at);
    assert.ok(time.title.length > time.textContent.length);
  }
});

test("Cover Letter Attachment stays in its Assistant Message, renders Markdown, and copies source", async () => {
  const item = attachment();
  const histories = [message(1, { content: "Draft ready.", attachments: [item] })];
  const artifacts = {
    cv: null,
    cover_letter: {
      id: item.artifact_id,
      type: item.type,
      version: item.version,
      title: item.title,
      draft: item.content,
      attachment: item,
    },
  };
  const { copied, dom } = await renderState(workspace({ histories, artifacts }));
  const { document } = dom.window;
  const messageNode = document.querySelector(".message.assistant");
  const attachmentNode = messageNode?.querySelector(".attachment.cover-letter");

  assert.ok(attachmentNode);
  assert.equal(document.querySelector(".timeline > .attachment"), null);
  assert.equal(attachmentNode.querySelector("h2")?.textContent, "Cover Letter");
  assert.equal(attachmentNode.querySelector("strong")?.textContent, "Hiring Manager");
  assert.equal(attachmentNode.querySelector("script"), null);
  attachmentNode.querySelector(".attachment-copy")?.click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(copied, [COVER_LETTER_MARKDOWN]);
});

test("CV Attachment opens the response URL safely and Side Panel has no preview constant", async () => {
  const responseUrl = "https://files.example.com/generated/cv-42?signature=response";
  const item = attachment({ type: "cv", content: responseUrl });
  const histories = [message(1, { content: "CV ready.", attachments: [item] })];
  const artifacts = {
    cv: {
      id: item.artifact_id,
      type: item.type,
      version: item.version,
      title: item.title,
      draft: "# Private CV draft",
      attachment: item,
    },
    cover_letter: null,
  };
  const { dom } = await renderState(workspace({ histories, artifacts }));
  const link = dom.window.document.querySelector(".attachment.cv .attachment-open");
  const source = await readFile(new URL("./sidepanel.js", import.meta.url), "utf8");

  assert.equal(link?.href, responseUrl);
  assert.equal(link?.target, "_blank");
  assert.match(link?.rel || "", /noopener/);
  assert.match(link?.rel || "", /noreferrer/);
  assert.doesNotMatch(source, /browser\.buildwithyang\.com/);
  assert.equal("CV_PREVIEW_URL" in sidepanel, false);
});

test("Action chips wrap near the composer and selection never clears shared history", async () => {
  const histories = [message(0), message(1)];
  const { dom, model } = await renderState(workspace({ histories }));
  const { document } = dom.window;
  const chips = [...document.querySelectorAll("#composer .action-chip")];

  assert.equal(chips.length, 2);
  chips[1].click();
  assert.equal(model.selectedActionId, "ask_more");
  assert.equal(document.querySelectorAll(".message").length, histories.length);
  assert.equal(chips[1].getAttribute("aria-pressed"), "true");

  const generic = await renderState(workspace({
    quickInsight: { title: "Page summary", cards: [] },
    actions: [{ id: "ask_more", title: "Ask More" }],
    selectedActionId: "ask_more",
  }));
  assert.deepEqual(
    [...generic.dom.window.document.querySelectorAll(".action-chip")].map((chip) => chip.textContent),
    ["Ask More"]
  );
});

test("update-required and retryable errors render distinct accessible composer states", async () => {
  assert.equal(typeof sidepanel.workspaceResponseError, "function");
  const updateUrl = "https://chromewebstore.google.com/detail/agent-bridge/id";
  const updateError = sidepanel.workspaceResponseError({
    ok: false,
    type: "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED",
    updateUrl,
    requiredVersion: 3,
  });
  const updated = await renderState(workspace(), { error: updateError });
  const updateRegion = updated.dom.window.document.querySelector("#composer-error");
  const updateLink = updateRegion?.querySelector("a");

  assert.equal(updateLink?.href, updateUrl);
  assert.equal(updateLink?.target, "_blank");
  assert.match(updateRegion?.textContent || "", /check the Gateway deployment/i);
  assert.doesNotMatch(updateRegion?.textContent || "", /sign in|log in|expired/i);
  assert.equal(updated.elements.messageInput.disabled, true);

  let retries = 0;
  const retryable = await renderState(workspace(), {
    error: sidepanel.workspaceResponseError({ ok: false, error: "Gateway unavailable" }),
    retry: () => { retries += 1; },
  });
  const retryRegion = retryable.dom.window.document.querySelector("#composer-error");
  assert.match(retryRegion?.textContent || "", /Gateway unavailable/);
  retryRegion?.querySelector("button")?.click();
  assert.equal(retries, 1);
  assert.equal(retryable.elements.messageInput.disabled, false);
});

test("composer keyboard policy sends Enter and preserves Shift+Enter", () => {
  assert.equal(typeof sidepanel.shouldSubmitMessage, "function");
  assert.equal(sidepanel.shouldSubmitMessage({ key: "Enter", shiftKey: false, isComposing: false }), true);
  assert.equal(sidepanel.shouldSubmitMessage({ key: "Enter", shiftKey: true, isComposing: false }), false);
  assert.equal(sidepanel.shouldSubmitMessage({ key: "Enter", shiftKey: false, isComposing: true }), false);
});

test("light responsive CSS contains horizontal overflow and keeps rich content local", async () => {
  const [html, css] = await Promise.all([
    readFile(new URL("./sidepanel.html", import.meta.url), "utf8"),
    readFile(new URL("./sidepanel.css", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(html, /brand-mark|signal-rule|connection-status/);
  assert.match(css, /color-scheme:\s*light/);
  assert.match(css, /html,\s*body\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.workspace-shell\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.action-chips\s*\{[^}]*flex-wrap:\s*wrap/s);
  assert.doesNotMatch(css, /\.action-chips\s*\{[^}]*overflow-x:\s*(?:auto|scroll)/s);
  assert.match(css, /\.markdown-content\s+table\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /\.markdown-content\s+pre\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /\.markdown-content\s+code\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /:focus-visible/);
});

test("Side Panel keeps lifecycle reloads, loading state, message limit, and auto-scroll", async () => {
  const source = await readFile(new URL("./sidepanel.js", import.meta.url), "utf8");
  const limited = await renderState(workspace({
    histories: Array.from({ length: 10 }, (_, index) => message(index)),
  }));

  assert.equal(limited.elements.messageInput.disabled, true);
  assert.equal(limited.elements.sendButton.disabled, true);
  assert.match(limited.elements.composerHint.textContent, /limit/i);
  assert.match(source, /AGENT_BRIDGE_WORKSPACE_UPDATED/);
  assert.match(source, /AGENT_BRIDGE_WORKSPACE_RESET/);
  assert.match(source, /chrome\.tabs\.onActivated\.addListener/);
  assert.match(source, /chrome\.tabs\.onActivated\.removeListener/);
  assert.match(source, /chrome\.runtime\.onMessage\.removeListener/);
  assert.match(source, /scrollTop\s*=\s*elements\.timeline\.scrollHeight/);
  assert.match(source, /import\s*\{\s*renderMarkdown\s*\}\s*from\s*"\.\/markdown\.js"/);
});
