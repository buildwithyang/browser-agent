import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import * as quickInsight from "./quick-insight.js";
import {
  ExtensionUpdateRequiredError,
  readGatewayResponse,
} from "./workspace-controller.js";

const {
  quickInsightActionErrorView,
  quickInsightView,
} = quickInsight;

/** Build one response-shaped Gateway fixture for protocol-boundary tests. */
function gatewayResponse({ status = 200, protocol = "4", body = {} } = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: () => protocol },
    json: async () => body,
  };
}

/** Convert one Gateway protocol failure through the initial Quick Insight view policy. */
async function initialRequestErrorView(response, lang) {
  try {
    await readGatewayResponse(response);
  } catch (error) {
    assert.ok(error instanceof ExtensionUpdateRequiredError);
    return quickInsight.quickInsightRequestErrorView(error, lang);
  }
  assert.fail("Expected the Gateway response to require an Extension update");
}

/** Create one externally controlled promise for request-ordering tests. */
function deferred() {
  let resolve;
  const promise = new Promise((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

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
    [{ id: "ask_more", title: "Ask more", prompt: "" }]
  );
  assert.equal(view.type, "summary");
  assert.equal(view.summaryHtml, "<p>Summary</p>");
  assert.equal(view.shortcuts[0].title, "Ask more");
});

test("upgrade-required Action errors present the Extension store link", () => {
  const updateUrl = "https://chromewebstore.google.com/detail/agent-bridge/id";
  assert.deepEqual(
    quickInsightActionErrorView({
      type: "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED",
      updateUrl,
      requiredVersion: 4,
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

test("initial Quick Insight 426 presents a localized Web Store update link", async () => {
  assert.equal(
    typeof quickInsight.quickInsightRequestErrorView,
    "function",
    "initial Quick Insight needs a structured request-error presenter"
  );
  const updateUrl = "https://chromewebstore.google.com/detail/agent-bridge/id";
  const view = await initialRequestErrorView(gatewayResponse({
    status: 426,
    body: {
      required_protocol_version: 4,
      update_url: updateUrl,
      message: "Upgrade required",
    },
  }), "en");

  assert.deepEqual(view, {
    errorTitle: "Update required",
    errorHint: "Update Agent Bridge to continue.",
    updateUrl,
    updateLabel: "Update extension",
    updateTarget: "_blank",
    updateRel: "noopener noreferrer",
  });
});

test("initial Quick Insight version mismatch uses the same localized update path", async () => {
  const view = await initialRequestErrorView(gatewayResponse({
    protocol: "1",
    body: { protocol_version: 1 },
  }), "zh");

  assert.equal(view.errorTitle, "需要更新");
  assert.equal(view.errorHint, "请更新 Agent Bridge 后继续。");
  assert.match(view.updateUrl, /^https:\/\/chromewebstore\.google\.com\//);
  assert.equal(view.updateTarget, "_blank");
  assert.equal(view.updateRel, "noopener noreferrer");
});

test("initial Quick Insight ordinary network errors keep the existing recovery hint", () => {
  const error = new TypeError("fetch failed");
  assert.deepEqual(quickInsight.quickInsightRequestErrorView(error, "en"), {
    errorHint: "无法连接网关 (fetch failed)。",
    errorCmd: "./dev-start backend",
  });
  assert.deepEqual(
    quickInsight.quickInsightRequestErrorView(
      Object.assign(new Error("aborted"), { name: "AbortError" }),
      "zh"
    ),
    {
      errorHint: "请求超时,网关无响应。",
      errorCmd: "./dev-start backend",
    }
  );
});

test("initial Quick Insight discards a response after the signed-in owner changes", async () => {
  assert.equal(
    typeof quickInsight.presentQuickInsightForCurrentOwner,
    "function",
    "initial Quick Insight needs an owner-guarded success presenter"
  );
  const response = deferred();
  const presented = [];
  let currentOwner = "owner-a";
  const request = response.promise.then((task) => (
    quickInsight.presentQuickInsightForCurrentOwner(task, {
      snapshot: { ownerId: "owner-a" },
      readCurrentSnapshot: async () => ({ ownerId: currentOwner }),
      present: (value) => presented.push(value),
    })
  ));

  currentOwner = "owner-b";
  response.resolve({ insight: { title: "Owner A private match" } });

  await assert.rejects(request, { name: "AuthSnapshotChangedError" });
  assert.deepEqual(presented, []);
});

test("initial Quick Insight presents a response exactly once for the same owner", async () => {
  const task = { insight: { title: "Current owner match" } };
  const presented = [];

  const result = await quickInsight.presentQuickInsightForCurrentOwner(task, {
    snapshot: { ownerId: "owner-a" },
    readCurrentSnapshot: async () => ({ ownerId: "owner-a" }),
    present: (value) => {
      presented.push(value);
      return true;
    },
  });

  assert.equal(result, true);
  assert.deepEqual(presented, [task]);
});

test("initial Quick Insight renders the structured update presentation", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /presentQuickInsightForCurrentOwner\(task,/);
  assert.match(source, /error instanceof AuthSnapshotChangedError/);
  assert.match(source, /quickInsightRequestErrorView\(error,\s*errLang\(lang\)\)/);
  assert.match(source, /if \(payload\.updateUrl\)/);
  assert.match(source, /updateLink\.target\s*=\s*payload\.updateTarget/);
  assert.match(source, /updateLink\.rel\s*=\s*payload\.updateRel/);
});

test("background renders normalized insight shortcuts", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /renderShortcuts\(body, payload\.insightView\.shortcuts\)/);
});

test("Quick Insight shortcut opens and prefills without executing Workspace", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(source, /type:\s*"AGENT_BRIDGE_OPEN_WORKSPACE"/);
  assert.match(source, /shortcut,/);
  assert.match(source, /shortcuts: payload\.shortcuts/);
  assert.match(source, /quickInsight: payload\.insight/);
  assert.doesNotMatch(source, /quick_insight_action/);
  assert.doesNotMatch(source, /runQuickInsightAction/);
  assert.match(source, /chrome\.sidePanel\.open\(\{ tabId \}\)/);
  assert.match(
    source,
    /chrome\.sidePanel\.setOptions\(\{\s*tabId,\s*path:\s*"sidepanel\.html",\s*enabled:\s*true/s
  );
  assert.match(source, /type:\s*"AGENT_BRIDGE_WORKSPACE_UPDATED",\s*tabId/s);
  assert.match(source, /workspaceSeedQueue\.run\(tabId/);
  assert.match(source, /workspaceSeedQueue\.run\(\s*message\.tabId/);
  assert.match(source, /readWorkspacePrefill\(message\.tabId/);
  assert.match(source, /acknowledgeWorkspacePrefill/);
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

test("Quick Insight shortcuts use wrapping content-width tags", async () => {
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
