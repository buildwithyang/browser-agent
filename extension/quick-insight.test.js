import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  quickInsightActionErrorView,
  quickInsightView,
  runQuickInsightAction,
} from "./quick-insight.js";

test("job insight normalizes generic cards for the existing renderer", () => {
  const view = quickInsightView({
    title: "Job Match",
    cards: [
      { type: "score", id: "decision", title: "Decision", score: 87, max_score: 100,
        recommendation: "apply", reason: "Core requirements match." },
      { type: "details", id: "job_overview", title: "Job Overview",
        items: [
          { label: "industry_business", value: "Fintech · B2B payments" },
          { label: "role_focus", value: "Transaction backend" },
        ], summary: "Build reliable payment services." },
      { type: "text", id: "top_strength", title: "Top Strength", body_html: "<p>Go</p>" },
      { type: "text", id: "top_gap", title: "Top Gap", body_html: "<p>Payments experience</p>" },
    ],
  }, []);
  assert.equal(view.score, 87);
  assert.equal(view.overview.roleFocus, "Transaction backend");
  assert.equal(view.topStrength, "Go");
});

test("summary card becomes summary HTML", () => {
  const view = quickInsightView(
    { title: "Page Summary", cards: [
      { type: "text", id: "summary", title: "Summary", body_html: "<p>Summary</p>" }
    ] },
    [{ id: "ask_more", title: "Ask more" }]
  );
  assert.equal(view.type, "summary");
  assert.equal(view.summaryHtml, "<p>Summary</p>");
  assert.equal(view.actions[0].title, "Ask more");
});

test("Quick Insight opens and seeds before its asynchronous Action request", async () => {
  const events = [];
  const result = await runQuickInsightAction("analyze", {
    openWorkspace: async () => {
      events.push("open-and-seed");
      return { state: { histories: [] }, lang: "en" };
    },
    executeOperation: async () => {
      events.push("request");
      return { state: { histories: [{ role: "assistant" }] }, lang: "en" };
    },
  });

  assert.deepEqual(events, ["open-and-seed", "request"]);
  assert.deepEqual(result.state.histories, [{ role: "assistant" }]);
});

test("Ask More only opens and focuses the shared Workspace", async () => {
  const events = [];
  await runQuickInsightAction("ask_more", {
    openWorkspace: async () => events.push("open-and-seed"),
    executeOperation: async () => events.push("request"),
  });
  assert.deepEqual(events, ["open-and-seed"]);
});

test("upgrade-required Action errors present the Extension store link", () => {
  const updateUrl = "https://chromewebstore.google.com/detail/agent-bridge/id";
  assert.deepEqual(
    quickInsightActionErrorView({
      type: "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED",
      updateUrl,
      requiredVersion: 3,
    }, "en"),
    {
      message: "Update Agent Bridge to continue.",
      updateUrl,
      updateLabel: "Update extension",
    }
  );
  assert.deepEqual(quickInsightActionErrorView({}, "zh"), {
    message: "Workspace 打开失败，请重试。",
    updateUrl: null,
    updateLabel: "",
  });
});

test("background renders normalized insight actions", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /renderActions\(body, payload\.insightView\.actions\)/);
});

test("Quick Insight actions open the shared Workspace", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /type:\s*"AGENT_BRIDGE_OPEN_WORKSPACE"/);
  assert.match(source, /actionId: message\.actionId/);
  assert.match(source, /chrome\.sidePanel\.open\(\{ tabId \}\)/);
  assert.match(
    source,
    /chrome\.sidePanel\.setOptions\(\{\s*tabId,\s*path:\s*"sidepanel\.html",\s*enabled:\s*true/s
  );
  assert.match(source, /type:\s*"AGENT_BRIDGE_WORKSPACE_UPDATED",\s*tabId/s);
  assert.match(source, /workspaceSeedQueue\.run\(tabId/);
  assert.match(source, /workspaceOperationQueue/);
  assert.match(source, /AGENT_BRIDGE_WORKSPACE_RESET/);
  assert.equal(source.includes(["AGENT_BRIDGE", "CONTINUE"].join("_")), false);
  assert.equal(source.includes(["current", "task"].join("-")), false);
  assert.equal(source.includes(["prior", "Result"].join("")), false);
});

test("content script supports fresh Workspace context collection", async () => {
  const source = await readFile(new URL("./content.js", import.meta.url), "utf8");
  assert.match(source, /AGENT_BRIDGE_COLLECT_CONTEXT/);
});

test("Quick Insight actions use wrapping content-width tags", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(
    source,
    /\.ab-actions\s*\{[^}]*display:\s*flex;[^}]*flex-wrap:\s*wrap;/s
  );
  assert.doesNotMatch(
    source,
    /\.ab-actions\s*\{[^}]*flex-direction:\s*column;/s
  );
  assert.match(source, /\.ab-action\s*\{[^}]*border-radius:\s*999px;/s);
  assert.match(source, /\.ab-action-err:empty\s*\{[^}]*display:\s*none;/s);
});
