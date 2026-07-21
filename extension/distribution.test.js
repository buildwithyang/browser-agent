import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const packageJson = JSON.parse(
  await readFile(new URL("./package.json", import.meta.url), "utf8")
);
const manifest = JSON.parse(
  await readFile(new URL("./manifest.json", import.meta.url), "utf8")
);

test("release metadata publishes Extension 0.3.0 consistently", () => {
  assert.equal(manifest.version, "0.3.0");
  assert.equal(packageJson.version, manifest.version);
});

test("package declares the Node versions shared by marked and jsdom", () => {
  assert.equal(packageJson.engines?.node, "^20.19.0 || ^22.13.0 || >=24.0.0");
});

test("install and ci prepare the committed Markdown vendor boundary", () => {
  assert.equal(packageJson.scripts?.prepare, "npm run sync:markdown-vendor");
});
