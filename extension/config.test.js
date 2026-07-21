import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import * as config from "./config.js";

const {
  DEFAULT_EXTENSION_UPDATE_URL,
  EXTENSION_PROTOCOL_HEADER,
  EXTENSION_PROTOCOL_VERSION,
  LOCAL_GATEWAY,
  PRODUCTION_GATEWAY,
  gatewayForEnvironment,
} = config;

test("source build defaults to local gateway", () => {
  assert.equal(gatewayForEnvironment(undefined), LOCAL_GATEWAY);
});

test("production environment selects cloud gateway", () => {
  assert.equal(gatewayForEnvironment("production"), PRODUCTION_GATEWAY);
});

test("wire protocol is independent from the manifest release version", async () => {
  const manifest = JSON.parse(await readFile(new URL("./manifest.json", import.meta.url), "utf8"));

  assert.equal(EXTENSION_PROTOCOL_VERSION, 4);
  assert.equal(EXTENSION_PROTOCOL_HEADER, "X-Agent-Bridge-Protocol-Version");
  assert.equal(manifest.version, "0.3.0");
  assert.notEqual(String(EXTENSION_PROTOCOL_VERSION), manifest.version);
});

test("extension update fallback targets the confirmed Chrome Web Store listing", () => {
  assert.equal(
    DEFAULT_EXTENSION_UPDATE_URL,
    "https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai"
  );
});
