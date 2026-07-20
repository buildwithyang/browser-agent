import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const packageJson = JSON.parse(
  await readFile(new URL("./package.json", import.meta.url), "utf8")
);

test("package declares the Node versions shared by marked and jsdom", () => {
  assert.equal(packageJson.engines?.node, "^20.19.0 || ^22.13.0 || >=24.0.0");
});

test("install and ci prepare the committed Markdown vendor boundary", () => {
  assert.equal(packageJson.scripts?.prepare, "npm run sync:markdown-vendor");
});
