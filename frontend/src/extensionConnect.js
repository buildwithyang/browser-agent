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

// issueToken: () => Promise<{token, user_id, expires_at}>
export async function connect({ sendMessage, extId, issueToken }) {
  const issued = await issueToken();
  const res = await sendMessage(extId, {
    type: "AUTH_TOKEN",
    token: issued.token,
    userId: issued.user_id,
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
