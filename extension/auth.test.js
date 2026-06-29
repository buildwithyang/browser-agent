import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildAuthHeaders,
  buildTaskBody,
  taskUrl,
  webBaseUrl,
  shouldClearToken,
  handleExternalMessage,
  TOKEN_KEY,
  EXPIRES_KEY,
  DEFAULT_GATEWAY,
} from "./auth.js";

function fakeStore(initial = {}) {
  const data = { ...initial };
  return {
    data,
    get: (key) => Promise.resolve(data[key]),
    set: (obj) => {
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

test("taskUrl trims trailing slash and appends /tasks", () => {
  assert.equal(taskUrl("http://127.0.0.1:17321"), "http://127.0.0.1:17321/tasks");
  assert.equal(taskUrl("https://x.com/api/"), "https://x.com/api/tasks");
  assert.equal(taskUrl(""), `${DEFAULT_GATEWAY}/tasks`);
});

test("webBaseUrl strips trailing /api and slashes", () => {
  assert.equal(webBaseUrl("https://browser.buildwithyang.com/api"), "https://browser.buildwithyang.com");
  assert.equal(webBaseUrl("https://browser.buildwithyang.com/api/"), "https://browser.buildwithyang.com");
  assert.equal(webBaseUrl("http://127.0.0.1:17321"), "http://127.0.0.1:17321");
  assert.equal(webBaseUrl(""), DEFAULT_GATEWAY.replace(/\/api$/, ""));
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

test("AUTH_TOKEN stores token+expiry and acks", async () => {
  const store = fakeStore();
  const res = await handleExternalMessage(
    { type: "AUTH_TOKEN", token: "abc", expiresAt: "2999-01-01T00:00:00Z" },
    { store, now: 1000 }
  );
  assert.deepEqual(res, { type: "AUTH_TOKEN_ACK", ok: true });
  assert.equal(store.data[TOKEN_KEY], "abc");
  assert.equal(store.data[EXPIRES_KEY], "2999-01-01T00:00:00Z");
});

test("unknown message returns undefined", async () => {
  assert.equal(await handleExternalMessage({ type: "NOPE" }, { store: fakeStore(), now: 1 }), undefined);
  assert.equal(await handleExternalMessage(null, { store: fakeStore(), now: 1 }), undefined);
});

test("buildTaskBody sets agent/lang and spreads payload", () => {
  const body = buildTaskBody(
    { url: "u", pageText: "p" },
    { agent: "job_match", lang: "zh" }
  );
  assert.equal(body.url, "u");
  assert.equal(body.pageText, "p");
  assert.equal(body.agent, "job_match");
  assert.equal(body.lang, "zh");
  assert.equal("sections" in body, false);
  assert.equal("priorResult" in body, false);
});

test("buildTaskBody includes sections and priorResult when given", () => {
  const body = buildTaskBody(
    { url: "u" },
    { agent: "job_match", lang: "en", sections: ["cover_letter", "resume_tips"], priorResult: "ANALYSIS" }
  );
  assert.deepEqual(body.sections, ["cover_letter", "resume_tips"]);
  assert.equal(body.priorResult, "ANALYSIS");
});
