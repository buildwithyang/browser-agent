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
