import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { quickInsightView } from "./quick-insight.js";

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

test("background renders normalized insight actions", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /renderActions\(body, payload\.insightView\.actions\)/);
});

test("Quick Insight actions open the shared Workspace", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /type:\s*"AGENT_BRIDGE_OPEN_WORKSPACE"/);
  assert.match(source, /actionId: message\.actionId/);
  assert.match(source, /chrome\.sidePanel\.open\(\{ tabId \}\)/);
  assert.equal(source.includes(["AGENT_BRIDGE", "CONTINUE"].join("_")), false);
  assert.equal(source.includes(["current", "task"].join("-")), false);
  assert.equal(source.includes(["prior", "Result"].join("")), false);
});

test("content script supports fresh Workspace context collection", async () => {
  const source = await readFile(new URL("./content.js", import.meta.url), "utf8");
  assert.match(source, /AGENT_BRIDGE_COLLECT_CONTEXT/);
});
