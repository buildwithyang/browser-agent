import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildAuthHeaders,
  buildQuickInsightBody,
  buildWorkspaceBody,
  taskUrl,
  webBaseUrl,
  loginStrings,
  LOCAL_WEB_URL,
  shouldClearToken,
  handleExternalMessage,
  TOKEN_KEY,
  EXPIRES_KEY,
  WORKSPACE_OWNER_KEY,
  DEFAULT_GATEWAY,
} from "./auth.js";

function fakeStore(initial = {}) {
  const data = { ...initial };
  const setCalls = [];
  return {
    data,
    setCalls,
    get: (key) => Promise.resolve(data[key]),
    set: (obj) => {
      setCalls.push(obj);
      Object.assign(data, obj);
      return Promise.resolve();
    },
  };
}

test("buildAuthHeaders adds bearer only when token present", () => {
  assert.deepEqual(buildAuthHeaders(""), { "Content-Type": "application/json" });
  assert.deepEqual(buildAuthHeaders("t"), {
    "Content-Type": "application/json",
    Authorization: "Bearer t",
  });
});

test("taskUrl routes each scenario to its explicit endpoint", () => {
  assert.equal(
    taskUrl("http://127.0.0.1:17321", "quick-insight"),
    "http://127.0.0.1:17321/tasks/quick-insight"
  );
  assert.equal(taskUrl("https://x.com/api/", "workspace"), "https://x.com/api/tasks/workspace");
  const removedEndpoint = ["current", "task"].join("-");
  assert.throws(() => taskUrl("https://x.com/api/", removedEndpoint), /endpoint/);
});

test("webBaseUrl strips trailing /api and slashes", () => {
  assert.equal(webBaseUrl("https://browser.buildwithyang.com/api"), "https://browser.buildwithyang.com");
  assert.equal(webBaseUrl("https://browser.buildwithyang.com/api/"), "https://browser.buildwithyang.com");
  assert.equal(webBaseUrl("http://localhost:5173/api"), "http://localhost:5173");
  assert.equal(webBaseUrl(""), LOCAL_WEB_URL);
});

test("webBaseUrl maps a bare local gateway to the frontend (gateway ≠ web origin)", () => {
  assert.equal(webBaseUrl("http://127.0.0.1:17321"), LOCAL_WEB_URL);
  assert.equal(webBaseUrl("http://127.0.0.1:17321/"), LOCAL_WEB_URL);
  assert.equal(webBaseUrl("http://localhost:17321"), LOCAL_WEB_URL);
});

test("loginStrings returns localized zh/en copy", () => {
  const zh = loginStrings("zh");
  assert.equal(zh.title, "需要登录");
  assert.match(zh.button, /登录/);
  assert.equal(zh.countdownTpl.replace("{n}", 5), "5 秒后自动打开登录页…");
  assert.equal(zh.text("http://x"), "Agent Bridge: 请前往 http://x 登录。");

  const en = loginStrings("en");
  assert.equal(en.title, "Sign-in required");
  assert.match(en.button, /sign-in/i);
  assert.match(en.countdownTpl.replace("{n}", 3), /Opening the sign-in page in 3s/);
  assert.match(en.text("http://x"), /sign in at http:\/\/x/);

  // 非 zh/en 归一化由调用方处理；这里默认走中文。
  assert.equal(loginStrings("auto").title, "需要登录");
});

test("shouldClearToken only on 401", () => {
  assert.equal(shouldClearToken(401), true);
  assert.equal(shouldClearToken(200), false);
  assert.equal(shouldClearToken(500), false);
});

test("PING reports connected=false when no token", async () => {
  const res = await handleExternalMessage({ type: "PING" }, { store: fakeStore(), now: 1000 });
  assert.deepEqual(res, { type: "PONG", connected: false });
});

test("PING reports connected=true for unexpired token", async () => {
  const store = fakeStore({ [TOKEN_KEY]: "t", [EXPIRES_KEY]: "2999-01-01T00:00:00Z" });
  const res = await handleExternalMessage({ type: "PING" }, { store, now: 1000 });
  assert.deepEqual(res, { type: "PONG", connected: true });
});

test("PING reports connected=false for expired token", async () => {
  const store = fakeStore({ [TOKEN_KEY]: "t", [EXPIRES_KEY]: "2000-01-01T00:00:00Z" });
  const res = await handleExternalMessage({ type: "PING" }, { store, now: Date.parse("2020-01-01") });
  assert.deepEqual(res, { type: "PONG", connected: false });
});

test("AUTH_TOKEN atomically stores token, expiry, and stable workspace owner", async () => {
  const store = fakeStore();
  const res = await handleExternalMessage(
    {
      type: "AUTH_TOKEN",
      token: "abc",
      expiresAt: "2999-01-01T00:00:00Z",
      userId: "user-1",
    },
    { store, now: 1000 }
  );
  assert.deepEqual(res, { type: "AUTH_TOKEN_ACK", ok: true });
  assert.equal(store.data[TOKEN_KEY], "abc");
  assert.equal(store.data[EXPIRES_KEY], "2999-01-01T00:00:00Z");
  assert.equal(store.data[WORKSPACE_OWNER_KEY], "user-1");
  assert.deepEqual(store.setCalls, [{
    [TOKEN_KEY]: "abc",
    [EXPIRES_KEY]: "2999-01-01T00:00:00Z",
    [WORKSPACE_OWNER_KEY]: "user-1",
  }]);
});

test("AUTH_TOKEN invalidates every active session namespace when owner changes", async () => {
  const store = fakeStore({ [WORKSPACE_OWNER_KEY]: "user-a" });
  const changes = [];

  const response = await handleExternalMessage(
    {
      type: "AUTH_TOKEN",
      token: "token-b",
      userId: "user-b",
    },
    {
      store,
      now: 1000,
      onOwnerChange: async (previousOwnerId, nextOwnerId) => {
        changes.push({ previousOwnerId, nextOwnerId });
      },
    }
  );

  assert.deepEqual(response, { type: "AUTH_TOKEN_ACK", ok: true });
  assert.deepEqual(changes, [{ previousOwnerId: "user-a", nextOwnerId: "user-b" }]);
  assert.equal(store.data[WORKSPACE_OWNER_KEY], "user-b");
});

test("AUTH_TOKEN rotation for the same owner keeps active session namespace", async () => {
  const store = fakeStore({ [WORKSPACE_OWNER_KEY]: "user-a" });
  let invalidations = 0;

  await handleExternalMessage(
    { type: "AUTH_TOKEN", token: "rotated", userId: "user-a" },
    {
      store,
      now: 1000,
      onOwnerChange: async () => {
        invalidations += 1;
      },
    }
  );

  assert.equal(invalidations, 0);
});

test("AUTH_TOKEN rejects a missing stable workspace owner", async () => {
  const store = fakeStore();
  const res = await handleExternalMessage(
    { type: "AUTH_TOKEN", token: "abc", expiresAt: "2999-01-01T00:00:00Z" },
    { store, now: 1000 }
  );
  assert.equal(res, undefined);
  assert.deepEqual(store.data, {});
});

test("AUTH_TOKEN rejects an empty bearer token", async () => {
  const store = fakeStore();
  const res = await handleExternalMessage(
    { type: "AUTH_TOKEN", token: "   ", userId: "user-1" },
    { store, now: 1000 }
  );
  assert.equal(res, undefined);
  assert.deepEqual(store.data, {});
});

test("unknown message returns undefined", async () => {
  assert.equal(await handleExternalMessage({ type: "NOPE" }, { store: fakeStore(), now: 1 }), undefined);
  assert.equal(await handleExternalMessage(null, { store: fakeStore(), now: 1 }), undefined);
});

test("Quick Insight request contains only page context and language", () => {
  const body = buildQuickInsightBody(
    {
      url: "u",
      title: "Page",
      selectedText: "selection",
      pageText: "page",
      imageText: "image",
      agent: "job_match",
      [["prior", "Result"].join("")]: "legacy",
    },
    "zh"
  );
  assert.deepEqual(body, {
    url: "u",
    title: "Page",
    selectedText: "selection",
    pageText: "page",
    imageText: "image",
    lang: "zh",
  });
});

test("Workspace request contains the complete public contract without agent", () => {
  const body = buildWorkspaceBody(
    { url: "u", title: "Page", pageText: "fresh", agent: "job_match" },
    {
      resourceUrl: "https://x/resource",
      actionId: "write_cover_letter",
      histories: [{ role: "assistant", content: "Earlier" }],
      currentDocument: {
        kind: "cover_letter",
        title: "Draft",
        text: "draft",
        html: "<p>draft</p>",
        sections: [],
      },
      message: "Improve it",
      lang: "en",
      [["prior", "Result"].join("")]: "legacy",
    }
  );
  assert.deepEqual(body, {
    url: "u",
    title: "Page",
    selectedText: "",
    pageText: "fresh",
    imageText: "",
    resourceUrl: "https://x/resource",
    actionId: "write_cover_letter",
    histories: [{ role: "assistant", content: "Earlier" }],
    currentDocument: { kind: "cover_letter", title: "Draft", text: "draft" },
    message: "Improve it",
    lang: "en",
  });
});
