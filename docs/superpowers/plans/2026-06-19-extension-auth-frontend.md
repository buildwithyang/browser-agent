# Extension Auth — Frontend + Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the browser extension to carry the gateway-issued bearer token, and add a frontend "浏览器扩展" card that mints + pushes that token via `externally_connectable`.

**Architecture:** Pure-logic modules (`extension/auth.js`, `frontend/src/extensionConnect.js`) hold all the testable behavior (message handling, header building, 401 handling, the 4-state machine) with dependencies injected, so they unit-test without a browser. The chrome-touching glue lives in `background.js` / `ExtensionCard.jsx`. The gateway is already implemented; this only integrates against its live endpoints.

**Tech Stack:** MV3 extension (ESM service worker), React 18 + Vite, `vitest` (frontend logic), Node built-in `node --test` (extension logic).

## Global Constraints

- Gateway endpoints already exist: `POST /auth/extension-token` → `{code,message,data:{token, expires_at}}`; `/tasks` accepts `Authorization: Bearer`.
- Domain: cloud single host `browser-agent.buildwithyang.com` (nginx: `/` static, `/api/*` → gateway). Local verify via `dev.buildwithyang.com` — **never `127.0.0.1`/`localhost`** in `externally_connectable` (rejects IPs/no-dot hosts).
- Extension `GATEWAY_URL` is configurable via `chrome.storage.local.gatewayUrl`, default `http://127.0.0.1:17321`; cloud value is `https://browser-agent.buildwithyang.com/api`; the extension appends `/tasks`.
- Token stored in `chrome.storage.local` (persistent).
- Message contract: `{type:"PING"}` → `{type:"PONG", connected}`; `{type:"AUTH_TOKEN", token, expiresAt}` → `{type:"AUTH_TOKEN_ACK", ok:true}`.
- **Never log the token** (`AGENTS.md` redaction rule).
- Verification split: automated = unit tests + `vite build`; the real browser e2e is a manual checklist (in the spec), the user runs it.
- Don't break existing extension behavior (context-menu → content.js → `/tasks` anonymous still works when no token).

---

### Task 1: Extension pure logic (`auth.js`) + node tests

**Files:**
- Create: `extension/package.json`
- Create: `extension/auth.js`
- Create: `extension/auth.test.js`

**Interfaces:**
- Produces (all ESM exports from `extension/auth.js`):
  - `TOKEN_KEY = "authToken"`, `EXPIRES_KEY = "authTokenExpiresAt"`, `GATEWAY_KEY = "gatewayUrl"`, `DEFAULT_GATEWAY = "http://127.0.0.1:17321"`
  - `buildAuthHeaders(token: string|null|undefined) -> {"Content-Type", ["Authorization"]}`
  - `taskUrl(base: string) -> string` (trims trailing `/`, appends `/tasks`)
  - `shouldClearToken(status: number) -> boolean`
  - `handleExternalMessage(msg, {store, now}) -> Promise<object|undefined>` where `store = {get(key)->Promise<any>, set(obj)->Promise<void>}`

- [ ] **Step 1: Write the failing test**

Create `extension/auth.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildAuthHeaders,
  taskUrl,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd extension && node --test`
Expected: FAIL — `Cannot find module '.../extension/auth.js'` (and no `package.json` yet means `import` may error). Both resolved next.

- [ ] **Step 3a: Add the package manifest for ESM + test script**

Create `extension/package.json`:

```json
{
  "name": "agent-bridge-extension",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test"
  }
}
```

- [ ] **Step 3b: Implement the pure logic**

Create `extension/auth.js`:

```js
// 纯逻辑：消息处理 / 鉴权头 / 网关地址 / 401 判定。无 chrome 依赖，便于 node --test。
export const TOKEN_KEY = "authToken";
export const EXPIRES_KEY = "authTokenExpiresAt";
export const GATEWAY_KEY = "gatewayUrl";
export const DEFAULT_GATEWAY = "http://127.0.0.1:17321";

export function buildAuthHeaders(token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export function taskUrl(base) {
  const root = (base || DEFAULT_GATEWAY).replace(/\/+$/, "");
  return `${root}/tasks`;
}

export function shouldClearToken(status) {
  return status === 401;
}

// store: { get(key) -> Promise<any>, set(obj) -> Promise<void> }；now: epoch ms。
// 返回要回给网页的响应对象（PING -> PONG / AUTH_TOKEN -> ACK），未知消息返回 undefined。
export async function handleExternalMessage(msg, { store, now }) {
  if (!msg || typeof msg !== "object") return undefined;

  if (msg.type === "PING") {
    const token = await store.get(TOKEN_KEY);
    const expiresAt = await store.get(EXPIRES_KEY);
    const connected = !!token && (!expiresAt || Date.parse(expiresAt) > now);
    return { type: "PONG", connected };
  }

  if (msg.type === "AUTH_TOKEN" && msg.token) {
    await store.set({ [TOKEN_KEY]: msg.token, [EXPIRES_KEY]: msg.expiresAt || null });
    return { type: "AUTH_TOKEN_ACK", ok: true };
  }

  return undefined;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd extension && node --test`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add extension/package.json extension/auth.js extension/auth.test.js
git commit -m "feat(extension): pure auth logic (message handling, headers, 401) + tests"
```

---

### Task 2: Wire `manifest.json` + `background.js` + popup

**Files:**
- Modify: `extension/manifest.json`
- Modify: `extension/background.js`
- Modify: `extension/popup.html`
- Modify: `extension/popup.js`

**Interfaces:**
- Consumes: `extension/auth.js` (Task 1).
- Produces: extension fetches `/tasks` with `Authorization: Bearer` when a token is stored; accepts `onMessageExternal` PING/AUTH_TOKEN; gateway base configurable in popup.

- [ ] **Step 1: Update the manifest**

Edit `extension/manifest.json` — make the background a module, broaden host_permissions, add externally_connectable:

```json
{
  "manifest_version": 3,
  "name": "Agent Bridge",
  "version": "0.1.0",
  "description": "Send the current webpage context to a local Python gateway.",
  "permissions": ["contextMenus", "activeTab", "scripting", "notifications", "storage"],
  "host_permissions": [
    "http://127.0.0.1:17321/*",
    "https://browser-agent.buildwithyang.com/*"
  ],
  "externally_connectable": {
    "matches": [
      "https://browser-agent.buildwithyang.com/*",
      "http://dev.buildwithyang.com/*"
    ]
  },
  "background": {
    "service_worker": "background.js",
    "type": "module"
  },
  "action": {
    "default_title": "Agent Bridge",
    "default_popup": "popup.html"
  }
}
```

- [ ] **Step 2: Verify the manifest is valid JSON**

Run: `cd extension && node -e "JSON.parse(require('fs').readFileSync('manifest.json','utf8')); console.log('manifest OK')"`
Expected: prints `manifest OK`.

- [ ] **Step 3: Wire background.js**

In `extension/background.js`, add an import at the very top (above `const GATEWAY_URL`), then replace the hardcoded URL and the fetch/response handling.

Add at line 1:

```js
import {
  buildAuthHeaders,
  taskUrl,
  shouldClearToken,
  handleExternalMessage,
  TOKEN_KEY,
  EXPIRES_KEY,
  GATEWAY_KEY,
  DEFAULT_GATEWAY,
} from "./auth.js";
```

Delete the line:

```js
const GATEWAY_URL = "http://127.0.0.1:17321/tasks";
```

Add a config reader near the other helpers (e.g. after `browserLang()`):

```js
// 网关基址可配置：cloud 填 https://browser-agent.buildwithyang.com/api，自部署默认本地。
function getGatewayConfig() {
  return chrome.storage.local
    .get({ [GATEWAY_KEY]: DEFAULT_GATEWAY, [TOKEN_KEY]: "" })
    .then((cfg) => ({ base: cfg[GATEWAY_KEY], token: cfg[TOKEN_KEY] }));
}
```

Replace the `resolveLang().then(...)` fetch chain (the block that builds and sends the request, currently starting `resolveLang().then((lang) => {`) with:

```js
  Promise.all([resolveLang(), getGatewayConfig()])
    .then(([lang, { base, token }]) => {
      console.log("[Agent Bridge] lang:", lang);
      return fetch(taskUrl(base), {
        method: "POST",
        headers: buildAuthHeaders(token),
        body: JSON.stringify({ ...message.payload, agent, lang }),
        signal: controller.signal,
      });
    })
    .then((response) => {
      console.log("[Agent Bridge] gateway responded:", response.status);
      if (shouldClearToken(response.status)) {
        // token 过期 / 被吊销：清掉本地 token，提示去网页端重新连接。
        chrome.storage.local.remove([TOKEN_KEY, EXPIRES_KEY]);
        clearTimeout(timeout);
        clearInterval(keepAlive);
        showResult(tabId, {
          state: "error",
          source: message.payload && message.payload.url,
          errorHint: "登录已过期或扩展被解绑,请在网页端重新登录并连接扩展。",
          text: "Agent Bridge: 请在网页端重新登录并连接扩展。",
        });
        return null;
      }
      return response.json();
    })
    .then((task) => {
      if (!task) return; // 401 already handled above
      clearTimeout(timeout);
      clearInterval(keepAlive);
      console.log("[Agent Bridge] task:", task.status, task.duration_ms + "ms");
      showResult(tabId, {
        state: "result",
        html: task.result_html,
        sections: task.sections || [],
        text: task.result || task.detail || "(no result)",
        source: (task.request && task.request.url) || (message.payload && message.payload.url),
        durationMs: task.duration_ms,
      });
    })
    .catch((error) => {
      clearTimeout(timeout);
      clearInterval(keepAlive);
      console.error("[Agent Bridge] gateway request failed:", error);
      const hint =
        error.name === "AbortError"
          ? "请求超时,网关无响应。"
          : "无法连接网关 (" + error.message + ")。";
      showResult(tabId, {
        state: "error",
        source: message.payload && message.payload.url,
        errorHint: hint,
        errorCmd: "cd gateway && uv run uvicorn app.main:app --host 127.0.0.1 --port 17321",
        text: "Agent Bridge 出错:" + hint,
      });
    });
```

(The `controller`, `timeout`, `keepAlive`, `tabId`, `agent`, `message` variables above this block are unchanged.)

Add the external message listener at the end of the file (after `renderPanel`):

```js
// 网页（externally_connectable.matches 内）推送 token / 探测连接。
chrome.runtime.onMessageExternal.addListener((msg, _sender, sendResponse) => {
  const store = {
    get: (key) => chrome.storage.local.get(key).then((obj) => obj[key]),
    set: (obj) => chrome.storage.local.set(obj),
  };
  handleExternalMessage(msg, { store, now: Date.now() }).then((res) => {
    if (res) sendResponse(res);
  });
  return true; // 异步 sendResponse
});
```

- [ ] **Step 4: Re-run extension tests (auth.js untouched) + manifest check**

Run: `cd extension && node --test && node -e "JSON.parse(require('fs').readFileSync('manifest.json','utf8')); console.log('manifest OK')"`
Expected: 8 tests PASS, `manifest OK`.

- [ ] **Step 5: Add the gateway-address field to the popup**

In `extension/popup.html`, add before the closing `</body>` (after the `hint` div, before the script tag):

```html
  <div class="label" style="margin-top:14px">网关地址 / Gateway URL</div>
  <input id="gateway" type="text" spellcheck="false"
    style="width:100%;box-sizing:border-box;padding:7px 10px;border:1px solid #2a2e39;border-radius:8px;background:#1b1e26;color:#e6e8ee;font-size:12px"
    placeholder="http://127.0.0.1:17321" />
  <div class="hint" id="gateway-hint">云端填 https://browser-agent.buildwithyang.com/api</div>
```

In `extension/popup.js`, append:

```js
// 网关地址（chrome.storage.local.gatewayUrl）；与 background.js 的 getGatewayConfig 对应。
const GATEWAY_KEY = "gatewayUrl";
const DEFAULT_GATEWAY = "http://127.0.0.1:17321";
const gatewayInput = document.getElementById("gateway");

chrome.storage.local.get({ [GATEWAY_KEY]: DEFAULT_GATEWAY }).then((cfg) => {
  gatewayInput.value = cfg[GATEWAY_KEY];
});

gatewayInput.addEventListener("change", () => {
  const value = gatewayInput.value.trim() || DEFAULT_GATEWAY;
  chrome.storage.local.set({ [GATEWAY_KEY]: value });
  gatewayInput.value = value;
});
```

- [ ] **Step 6: Commit**

```bash
git add extension/manifest.json extension/background.js extension/popup.html extension/popup.js
git commit -m "feat(extension): bearer token on /tasks, onMessageExternal, configurable gateway"
```

---

### Task 3: Frontend connection logic (`extensionConnect.js`) + vitest

**Files:**
- Modify: `frontend/package.json` (add `vitest` devDep + `test` script)
- Modify: `frontend/vite.config.js` (add `test` block)
- Create: `frontend/src/extensionConnect.js`
- Create: `frontend/src/extensionConnect.test.js`

**Interfaces:**
- Produces (ESM exports from `frontend/src/extensionConnect.js`):
  - `EXT_STATE = { DETECTING, NOT_INSTALLED, NOT_CONNECTED, CONNECTED }` (string values `"detecting"|"not_installed"|"not_connected"|"connected"`)
  - `probe({sendMessage, extId}) -> Promise<{installed: boolean, connected: boolean}>`
  - `connect({sendMessage, extId, issueToken}) -> Promise<{ok: boolean, expiresAt: string|null}>`
  - `probeThenAutoConnect({sendMessage, extId, issueToken}) -> Promise<{state, expiresAt?}>`
  - `sendMessage` shape: `(extId, msg) => Promise<response>`; `issueToken` shape: `() => Promise<{token, expires_at}>`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/extensionConnect.test.js`:

```js
import { describe, test, expect } from "vitest";

import {
  EXT_STATE,
  probe,
  connect,
  probeThenAutoConnect,
} from "./extensionConnect.js";

const EXT_ID = "abcdef";

describe("probe", () => {
  test("PONG connected -> installed+connected", async () => {
    const sendMessage = async () => ({ type: "PONG", connected: true });
    expect(await probe({ sendMessage, extId: EXT_ID })).toEqual({ installed: true, connected: true });
  });

  test("PONG not connected -> installed, not connected", async () => {
    const sendMessage = async () => ({ type: "PONG", connected: false });
    expect(await probe({ sendMessage, extId: EXT_ID })).toEqual({ installed: true, connected: false });
  });

  test("throw / no extension -> not installed", async () => {
    const sendMessage = async () => {
      throw new Error("no-extension");
    };
    expect(await probe({ sendMessage, extId: EXT_ID })).toEqual({ installed: false, connected: false });
  });
});

describe("connect", () => {
  test("issues token, pushes, returns ok on ack", async () => {
    const calls = [];
    const issueToken = async () => ({ token: "T", expires_at: "2999-01-01T00:00:00Z" });
    const sendMessage = async (extId, msg) => {
      calls.push(msg);
      return { type: "AUTH_TOKEN_ACK", ok: true };
    };
    const res = await connect({ sendMessage, extId: EXT_ID, issueToken });
    expect(res).toEqual({ ok: true, expiresAt: "2999-01-01T00:00:00Z" });
    expect(calls[0]).toEqual({ type: "AUTH_TOKEN", token: "T", expiresAt: "2999-01-01T00:00:00Z" });
  });

  test("no ack -> ok false", async () => {
    const issueToken = async () => ({ token: "T", expires_at: null });
    const sendMessage = async () => ({ type: "PONG" });
    expect((await connect({ sendMessage, extId: EXT_ID, issueToken })).ok).toBe(false);
  });
});

describe("probeThenAutoConnect", () => {
  test("not installed", async () => {
    const sendMessage = async () => {
      throw new Error("x");
    };
    const res = await probeThenAutoConnect({ sendMessage, extId: EXT_ID, issueToken: async () => ({}) });
    expect(res.state).toBe(EXT_STATE.NOT_INSTALLED);
  });

  test("already connected -> no token issued", async () => {
    let issued = false;
    const sendMessage = async () => ({ type: "PONG", connected: true });
    const issueToken = async () => {
      issued = true;
      return {};
    };
    const res = await probeThenAutoConnect({ sendMessage, extId: EXT_ID, issueToken });
    expect(res.state).toBe(EXT_STATE.CONNECTED);
    expect(issued).toBe(false);
  });

  test("installed not connected -> auto connect succeeds", async () => {
    let pinged = false;
    const sendMessage = async (extId, msg) => {
      if (msg.type === "PING") {
        pinged = true;
        return { type: "PONG", connected: false };
      }
      return { type: "AUTH_TOKEN_ACK", ok: true };
    };
    const issueToken = async () => ({ token: "T", expires_at: "2999-01-01T00:00:00Z" });
    const res = await probeThenAutoConnect({ sendMessage, extId: EXT_ID, issueToken });
    expect(pinged).toBe(true);
    expect(res.state).toBe(EXT_STATE.CONNECTED);
  });

  test("auto connect fails -> not connected", async () => {
    const sendMessage = async (extId, msg) =>
      msg.type === "PING" ? { type: "PONG", connected: false } : { type: "PONG" };
    const issueToken = async () => ({ token: "T", expires_at: null });
    const res = await probeThenAutoConnect({ sendMessage, extId: EXT_ID, issueToken });
    expect(res.state).toBe(EXT_STATE.NOT_CONNECTED);
  });
});
```

- [ ] **Step 2: Add vitest dependency + script + config**

Install the dev dependency:

Run: `cd frontend && npm install -D vitest`
Expected: adds `vitest` to `devDependencies`, updates `package-lock.json`.

In `frontend/package.json`, add a `test` script to the `scripts` block:

```json
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
```

In `frontend/vite.config.js`, add a `test` block inside the `defineConfig({...})` object (sibling of `plugins` / `server`):

```js
  test: {
    environment: "node",
    include: ["src/**/*.test.js"],
  },
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `./extensionConnect.js`.

- [ ] **Step 4: Implement the connection logic**

Create `frontend/src/extensionConnect.js`:

```js
// 纯逻辑：探测扩展 / 推送 token / 4 态计算。chrome 与 fetch 由调用方注入，便于 vitest。
export const EXT_STATE = {
  DETECTING: "detecting",
  NOT_INSTALLED: "not_installed",
  NOT_CONNECTED: "not_connected",
  CONNECTED: "connected",
};

// sendMessage: (extId, msg) => Promise<response>
export async function probe({ sendMessage, extId }) {
  try {
    const res = await sendMessage(extId, { type: "PING" });
    if (res && res.type === "PONG") {
      return { installed: true, connected: !!res.connected };
    }
    return { installed: false, connected: false };
  } catch {
    return { installed: false, connected: false };
  }
}

// issueToken: () => Promise<{token, expires_at}>
export async function connect({ sendMessage, extId, issueToken }) {
  const issued = await issueToken();
  const res = await sendMessage(extId, {
    type: "AUTH_TOKEN",
    token: issued.token,
    expiresAt: issued.expires_at ?? null,
  });
  const ok = !!(res && res.type === "AUTH_TOKEN_ACK" && res.ok);
  return { ok, expiresAt: issued.expires_at ?? null };
}

export async function probeThenAutoConnect(deps) {
  const p = await probe(deps);
  if (!p.installed) return { state: EXT_STATE.NOT_INSTALLED };
  if (p.connected) return { state: EXT_STATE.CONNECTED };
  try {
    const c = await connect(deps);
    return c.ok
      ? { state: EXT_STATE.CONNECTED, expiresAt: c.expiresAt }
      : { state: EXT_STATE.NOT_CONNECTED };
  } catch {
    return { state: EXT_STATE.NOT_CONNECTED };
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (9 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.js frontend/src/extensionConnect.js frontend/src/extensionConnect.test.js
git commit -m "feat(frontend): extension connect logic (probe/connect/state) + vitest"
```

---

### Task 4: Frontend API + "浏览器扩展" card

**Files:**
- Modify: `frontend/src/api.js` (add `issueExtensionToken`)
- Create: `frontend/src/ExtensionCard.jsx`
- Modify: `frontend/src/App.jsx` (render the card in the logged-in block)

**Interfaces:**
- Consumes: `extensionConnect.js` (Task 3), the gateway `POST /api/auth/extension-token`.
- Produces: `issueExtensionToken() -> Promise<{token, expires_at}>`; `<ExtensionCard />` React component.

- [ ] **Step 1: Add the API call**

In `frontend/src/api.js`, add after `export function fetchMe() {...}`:

```js
export function issueExtensionToken() {
  return call("/auth/extension-token", { method: "POST" });
}
```

- [ ] **Step 2: Create the card component**

Create `frontend/src/ExtensionCard.jsx`:

```jsx
import { useCallback, useEffect, useState } from "react";

import { issueExtensionToken } from "./api.js";
import { EXT_STATE, probeThenAutoConnect, connect } from "./extensionConnect.js";

const EXT_ID = import.meta.env.VITE_EXTENSION_ID || "";

// 包一层 Promise 的 chrome.runtime.sendMessage（仅此处碰真实 chrome API）。
function sendMessage(extId, msg) {
  return new Promise((resolve, reject) => {
    const runtime = typeof chrome !== "undefined" && chrome.runtime;
    if (!runtime || !runtime.sendMessage || !extId) {
      reject(new Error("no-extension"));
      return;
    }
    try {
      runtime.sendMessage(extId, msg, (res) => {
        const err = chrome.runtime.lastError;
        if (err) reject(new Error(err.message));
        else resolve(res);
      });
    } catch (e) {
      reject(e);
    }
  });
}

const LABEL = {
  [EXT_STATE.DETECTING]: "检测中…",
  [EXT_STATE.NOT_INSTALLED]: "未检测到扩展",
  [EXT_STATE.NOT_CONNECTED]: "扩展已安装，未连接",
  [EXT_STATE.CONNECTED]: "已连接",
};

export default function ExtensionCard() {
  const [state, setState] = useState(EXT_STATE.DETECTING);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const deps = { sendMessage, extId: EXT_ID, issueToken: issueExtensionToken };

  const autoConnect = useCallback(async () => {
    setError("");
    const res = await probeThenAutoConnect(deps);
    setState(res.state);
  }, []);

  useEffect(() => {
    autoConnect();
  }, [autoConnect]);

  const onConnect = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await connect(deps);
      setState(res.ok ? EXT_STATE.CONNECTED : EXT_STATE.NOT_CONNECTED);
      if (!res.ok) setError("连接未被扩展确认，请重试。");
    } catch {
      setError("连接失败：请确认已安装扩展，且当前页面在扩展允许的域名下。");
      setState(EXT_STATE.NOT_INSTALLED);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="uploader-head">
        <div>
          <h2>浏览器扩展</h2>
          <p className="muted">连接后，扩展将以你的身份调用网关、使用你的简历。</p>
        </div>
        {state === EXT_STATE.CONNECTED ? (
          <span className="badge badge-ok">已连接 ✓</span>
        ) : (
          <button className="btn-primary" onClick={onConnect} disabled={busy || state === EXT_STATE.DETECTING}>
            {busy ? "连接中…" : state === EXT_STATE.NOT_CONNECTED ? "连接扩展" : "重新连接"}
          </button>
        )}
      </div>
      <p className="muted">{LABEL[state]}</p>
      {state === EXT_STATE.NOT_INSTALLED && (
        <p className="muted">未检测到扩展。请先安装 Agent Bridge 扩展并刷新本页。</p>
      )}
      {error && <div className="alert alert-error">{error}</div>}
    </section>
  );
}
```

- [ ] **Step 3: Render it in App.jsx**

In `frontend/src/App.jsx`, add the import near the top imports:

```jsx
import ExtensionCard from "./ExtensionCard.jsx";
```

Render the card inside the logged-in block, right after the uploader `</section>` and before `{error && ...}` (i.e. between the upload card and the alerts):

```jsx
            </section>

            <ExtensionCard />

            {error && <div className="alert alert-error">{error}</div>}
```

(The existing `</section>` shown is the closing tag of the `card uploader` section; insert `<ExtensionCard />` immediately after it.)

- [ ] **Step 4: Verify the build + tests**

Run: `cd frontend && npm test && npm run build`
Expected: tests PASS (9), `vite build` completes and writes `dist/` with no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.js frontend/src/ExtensionCard.jsx frontend/src/App.jsx
git commit -m "feat(frontend): 浏览器扩展 connection card + issueExtensionToken"
```

---

### Task 5: Docs — extension ID env + READMEs

**Files:**
- Modify: `frontend/.env.example` (add `VITE_EXTENSION_ID`)
- Modify: `extension/README.md`
- Modify: `frontend/README.md`
- Modify: `docs/superpowers/specs/2026-06-16-extension-auth-design.md` (tick frontend/extension steps)

**Interfaces:** none (docs/config only).

- [ ] **Step 1: Add the extension-ID env var**

In `frontend/.env.example`, add:

```bash
# 已安装的 Agent Bridge 扩展 ID（前端据此用 chrome.runtime.sendMessage 推送登录 token）。
# 加载 unpacked 扩展后在 chrome://extensions 复制其 ID 填入；同一路径下 ID 稳定。
VITE_EXTENSION_ID=
```

- [ ] **Step 2: Document the new behavior in the extension README**

In `extension/README.md`, replace the line that says the gateway URL is fixed (around line 12, `网关地址固定为 ...`) with:

```markdown
网关地址可在扩展弹窗（popup）配置，存于 `chrome.storage.local.gatewayUrl`，默认 `http://127.0.0.1:17321`；云端填 `https://browser-agent.buildwithyang.com/api`。登录态下，前端「浏览器扩展」卡片会把 bearer token 推送给扩展，之后 `/tasks` 自动带 `Authorization: Bearer`。遇 401（token 过期/被解绑）扩展会清除本地 token 并提示在网页端重新连接。

扩展逻辑测试：`cd extension && node --test`。
```

- [ ] **Step 3: Document VITE_EXTENSION_ID in the frontend README**

In `frontend/README.md`, add under the env-config section (near the `VITE_GATEWAY_URL` mention):

```markdown
- `VITE_EXTENSION_ID`：已安装扩展的 ID，用于把登录 token 推送给扩展。加载 unpacked 扩展后从 `chrome://extensions` 复制。
  > ⚠️ 验证扩展连接时前端必须跑在 `dev.buildwithyang.com:5173`（`npm run dev` 已配该域名），**不能用 `127.0.0.1`**——`externally_connectable` 不匹配 IP。

前端逻辑测试：`npm test`（vitest）。
```

- [ ] **Step 4: Tick the spec checkboxes**

In `docs/superpowers/specs/2026-06-16-extension-auth-design.md`, under "## 实施步骤", change the now-done frontend/extension items from `- [ ]` to `- [x]`:
- 扩展：manifest / auth.js+tests / background+popup
- 前端：extensionConnect+tests / App.jsx 卡片
- 验证：`npm test` / `node --test` / `npm run build`
- 文档：README 更新

Leave the deferred "已连接设备 UI" item unchecked.

- [ ] **Step 5: Final automated gates + commit**

Run all automated gates together:

Run: `cd extension && node --test && cd ../frontend && npm test && npm run build`
Expected: extension 8 tests PASS, frontend 9 tests PASS, build succeeds.

```bash
git add frontend/.env.example extension/README.md frontend/README.md docs/superpowers/specs/2026-06-16-extension-auth-design.md
git commit -m "docs: extension ID env + README/spec updates for extension auth"
```

---

## Self-Review

**Spec coverage:**
- `manifest.json` externally_connectable / host_permissions / module worker → Task 2 ✅
- Configurable `GATEWAY_URL` (cloud `/api`, default local) → Task 2 (`getGatewayConfig`, popup) ✅
- `onMessageExternal` PING/PONG{connected} + AUTH_TOKEN/ACK → Task 1 (logic) + Task 2 (listener) ✅
- `/tasks` bearer header + 401 clear+reconnect hint → Task 2 ✅
- token in `chrome.storage.local` → Task 1/2 ✅
- Frontend `issueExtensionToken` (`/api/auth/extension-token`) → Task 4 ✅
- `extensionConnect.js` pure logic + 4-state machine + hybrid auto/manual → Task 3 (logic) + Task 4 (card UI) ✅
- `VITE_EXTENSION_ID` → Task 4 (consumed) + Task 5 (documented) ✅
- Verification: vitest + `node --test` + build → Tasks 1,3,4,5 ✅; manual checklist lives in spec ✅
- Deferred device-unbinding UI → intentionally not implemented ✅

**Placeholder scan:** No TBD/TODO; every code step is complete. The `key`/fixed-ID is intentionally deferred (unpacked ID is path-stable; documented in Task 5), not a placeholder.

**Type consistency:** `sendMessage(extId,msg)->Promise`, `issueToken()->{token,expires_at}`, `probe->{installed,connected}`, `connect->{ok,expiresAt}`, message types `PING`/`PONG`/`AUTH_TOKEN`/`AUTH_TOKEN_ACK`, storage keys `authToken`/`authTokenExpiresAt`/`gatewayUrl` all consistent between `extension/auth.js`, `background.js`, `extensionConnect.js`, and `ExtensionCard.jsx`. ✅
