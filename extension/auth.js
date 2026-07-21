import {
  EXTENSION_PROTOCOL_HEADER,
  EXTENSION_PROTOCOL_VERSION,
  GATEWAY_BASE as DEFAULT_GATEWAY,
} from "./config.js";

// 纯逻辑：消息处理 / 鉴权头 / 网关地址 / 401 判定。无 chrome 依赖，便于 node --test。
export const TOKEN_KEY = "authToken";
export const EXPIRES_KEY = "authTokenExpiresAt";
export const WORKSPACE_OWNER_KEY = "workspaceOwnerId";
export { DEFAULT_GATEWAY };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Build versioned JSON headers, adding bearer authentication only when available. */
export function buildAuthHeaders(token) {
  const headers = {
    "Content-Type": "application/json",
    [EXTENSION_PROTOCOL_HEADER]: String(EXTENSION_PROTOCOL_VERSION),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

/** Build versioned Workspace headers that explicitly negotiate an NDJSON response. */
export function buildWorkspaceHeaders(token) {
  return {
    ...buildAuthHeaders(token),
    Accept: "application/x-ndjson",
  };
}

export function taskUrl(base, endpoint) {
  if (endpoint !== "quick-insight" && endpoint !== "workspace") {
    throw new TypeError("endpoint must be quick-insight or workspace");
  }
  const root = (base || DEFAULT_GATEWAY).replace(/\/+$/, "");
  return `${root}/tasks/${endpoint}`;
}

// 本地开发前端(Vite)地址；自部署裸网关(127.0.0.1:17321)与前端不同源，按此约定跳转。
export const LOCAL_WEB_URL = "http://localhost:5173";

// 从网关基址推导网页端(前端)地址，用于 401 时给用户一个登录入口；登录后自动回连扩展。
//   云端         https://host/api            -> https://host
//   Vite 代理    http://localhost:5173/api   -> http://localhost:5173
//   裸网关(本地) http://127.0.0.1:17321      -> http://localhost:5173（网关≠前端，按约定映射）
//   其他无 /api 的地址原样返回（尽力而为）。
export function webBaseUrl(base) {
  const root = (base || DEFAULT_GATEWAY).replace(/\/+$/, "");
  if (/\/api$/.test(root)) return root.replace(/\/api$/, "");
  if (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(root)) return LOCAL_WEB_URL;
  return root;
}

// 401 面板文案（zh/en）。纯函数便于单测；background 传入已归一化为 zh/en 的值。
// text() 接收登录地址，返回纯文本兜底（无 DOM 时使用）。
export function loginStrings(lang) {
  if (lang === "en") {
    return {
      title: "Sign-in required",
      hint: "Your session has expired. Sign in on the web to reconnect the extension:",
      button: "Go to sign-in →",
      countdownTpl: "Opening the sign-in page in {n}s…",
      opened: "Sign-in page opened.",
      text: (url) => "Agent Bridge: please sign in at " + url,
    };
  }
  return {
    title: "需要登录",
    hint: "登录已过期，请在网页端重新登录以重连扩展：",
    button: "去登录 →",
    countdownTpl: "{n} 秒后自动打开登录页…",
    opened: "已为你打开登录页。",
    text: (url) => "Agent Bridge: 请前往 " + url + " 登录。",
  };
}

/** Copy the public PageContext fields while dropping legacy or internal fields. */
function pageContextBody(payload = {}) {
  return {
    url: typeof payload.url === "string" ? payload.url : "",
    title: typeof payload.title === "string" ? payload.title : "",
    selectedText: typeof payload.selectedText === "string" ? payload.selectedText : "",
    pageText: typeof payload.pageText === "string" ? payload.pageText : "",
    imageText: typeof payload.imageText === "string" ? payload.imageText : "",
    intent: typeof payload.intent === "string" ? payload.intent : "Summarize this page.",
  };
}

/** Build the public Quick Insight request without exposing an Agent selector. */
export function buildQuickInsightBody(payload, lang) {
  return { ...pageContextBody(payload), lang };
}

/** Copy only the two fixed Workspace Artifact slots. */
function artifactBody(artifacts) {
  const source = artifacts && typeof artifacts === "object" ? artifacts : {};
  return {
    cv: source.cv ?? null,
    cover_letter: source.cover_letter ?? null,
  };
}

/** Build one stateless Workspace transition from fresh page context and local state. */
export function buildWorkspaceBody(pageContext, workspace = {}) {
  if (typeof workspace.operationId !== "string" || !UUID_PATTERN.test(workspace.operationId)) {
    throw new TypeError("Workspace operationId must be a UUID");
  }
  if (typeof workspace.message !== "string" || !workspace.message.trim()) {
    throw new TypeError("Workspace message is required");
  }
  const body = {
    ...pageContextBody(pageContext),
    operationId: workspace.operationId,
    resourceUrl: workspace.resourceUrl,
    histories: Array.isArray(workspace.histories) ? workspace.histories : [],
    artifacts: artifactBody(workspace.artifacts),
    lang: workspace.lang,
  };
  body.message = workspace.message;
  return body;
}

/** Build one composer SEND from the latest complete local Workspace state. */
export function buildUserMessageWorkspaceBody(pageContext, options = {}) {
  const state = options.state && typeof options.state === "object" ? options.state : {};
  return buildWorkspaceBody(pageContext, {
    operationId: options.operationId,
    resourceUrl: options.resourceUrl,
    histories: state.histories,
    artifacts: state.artifacts,
    message: options.message,
    lang: options.lang,
  });
}

export function shouldClearToken(status) {
  return status === 401;
}

// store: { get(key) -> Promise<any>, set(obj) -> Promise<void> }；now: epoch ms。
// 返回要回给网页的响应对象（PING -> PONG / AUTH_TOKEN -> ACK），未知消息返回 undefined。
export async function handleExternalMessage(msg, { store, now, onOwnerChange }) {
  if (!msg || typeof msg !== "object") return undefined;

  if (msg.type === "PING") {
    const token = await store.get(TOKEN_KEY);
    const expiresAt = await store.get(EXPIRES_KEY);
    const connected = !!token && (!expiresAt || Date.parse(expiresAt) > now);
    return { type: "PONG", connected };
  }

  if (
    msg.type === "AUTH_TOKEN"
    && typeof msg.token === "string"
    && msg.token.trim()
    && typeof msg.userId === "string"
    && msg.userId.trim()
  ) {
    const previousOwnerId = await store.get(WORKSPACE_OWNER_KEY);
    const nextOwnerId = msg.userId.trim();
    if (previousOwnerId !== nextOwnerId && typeof onOwnerChange === "function") {
      await onOwnerChange(previousOwnerId, nextOwnerId);
    }
    // One storage write keeps an extension-token rotation bound to the same owner.
    await store.set({
      [TOKEN_KEY]: msg.token.trim(),
      [EXPIRES_KEY]: msg.expiresAt || null,
      [WORKSPACE_OWNER_KEY]: nextOwnerId,
    });
    return { type: "AUTH_TOKEN_ACK", ok: true };
  }

  return undefined;
}
