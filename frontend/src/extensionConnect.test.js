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
