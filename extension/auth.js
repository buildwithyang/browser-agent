// 纯逻辑：消息处理 / 鉴权头 / 网关地址 / 401 判定。无 chrome 依赖，便于 node --test。
export const TOKEN_KEY = "authToken";
export const EXPIRES_KEY = "authTokenExpiresAt";
export const GATEWAY_KEY = "gatewayUrl";
// 默认走云端;自部署在扩展弹窗里改成本地 http://127.0.0.1:17321。
export const DEFAULT_GATEWAY = "https://browser.buildwithyang.com/api";

export function buildAuthHeaders(token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export function taskUrl(base) {
  const root = (base || DEFAULT_GATEWAY).replace(/\/+$/, "");
  return `${root}/tasks`;
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

// Build the JSON body for a /tasks request. `opts.sections` / `opts.priorResult`
// are the on-demand follow-up fields (omitted entirely for the stage-one request).
export function buildTaskBody(payload, { agent, lang, sections, priorResult } = {}) {
  const body = { ...payload, agent, lang };
  if (sections) body.sections = sections;
  if (priorResult) body.priorResult = priorResult;
  return body;
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
