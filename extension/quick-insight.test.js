import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { quickInsightView } from "./quick-insight.js";

test("job insight keeps typed decision fields", () => {
  const view = quickInsightView({
    type: "job_match",
    title: "Job Match",
    score: 87,
    recommendation: "apply",
    reason: "Core requirements match.",
    job_overview: {
      industry_business: "Fintech · B2B payments",
      role_focus: "Transaction backend",
      summary: "Build reliable payment services.",
    },
    top_strength: "Go",
    top_gap: "Payments experience",
  }, []);
  assert.equal(view.score, 87);
  assert.equal(view.overview.roleFocus, "Transaction backend");
});

test("disabled actions are omitted", () => {
  const view = quickInsightView(
    { type: "summary", title: "Page Summary", summary_html: "<p>Summary</p>" },
    [{ id: "ask_more", label: "Ask more", enabled: false }]
  );
  assert.deepEqual(view.actions, []);
});

test("background renders normalized insight actions", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /renderActions\(body, payload\.insightView\.actions\)/);
});

test("continuation uses the routed response agent", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /agent: task\.request\?\.agent \|\| agent/);
});
