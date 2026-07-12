import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("popup exposes language only", async () => {
  const [html, js] = await Promise.all([
    readFile(new URL("./popup.html", import.meta.url), "utf8"),
    readFile(new URL("./popup.js", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(html, /Gateway URL|网关地址|id="gateway"/);
  assert.doesNotMatch(js, /gatewayInput|GATEWAY_KEY|gatewayUrl/);
  assert.match(html, /Output language/);
  assert.match(js, /langPref/);
});
