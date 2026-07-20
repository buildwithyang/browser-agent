import { test } from "node:test";
import assert from "node:assert/strict";

import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const ZIP_PATH = new URL("../dist/agent-bridge-extension.zip", import.meta.url);

/** List normalized file paths stored in the packaged extension zip. */
async function listArchiveEntries() {
  const { stdout } = await execFileAsync("unzip", ["-Z1", ZIP_PATH.pathname]);
  return stdout.trim().split("\n").filter(Boolean);
}

/** Extract the package into a disposable directory for import-graph checks. */
async function extractArchive() {
  const directory = await mkdtemp(path.join(tmpdir(), "agent-bridge-package-"));
  await execFileAsync("unzip", ["-q", ZIP_PATH.pathname, "-d", directory]);
  return directory;
}

/** Run one package assertion against an extracted archive and always clean it up. */
async function withExtractedArchive(operation) {
  const root = await extractArchive();
  try {
    await operation(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

/** Return static relative imports declared by one JavaScript module. */
function relativeImports(source) {
  return [...source.matchAll(/(?:import|export)\s+(?:[^"']*?\s+from\s+)?["'](\.[^"']+)["']/g)]
    .map((match) => match[1]);
}

/** Traverse the Side Panel module graph and assert every relative import exists. */
async function assertSidePanelImportsResolve(root) {
  const html = await readFile(path.join(root, "sidepanel.html"), "utf8");
  const entryMatch = html.match(/<script\s+type=["']module["']\s+src=["']([^"']+)["']/);
  assert.ok(entryMatch, "sidepanel.html must declare a module entry point");

  const pending = [path.resolve(root, entryMatch[1])];
  const visited = new Set();
  while (pending.length) {
    const modulePath = pending.pop();
    if (visited.has(modulePath)) continue;
    visited.add(modulePath);

    const source = await readFile(modulePath, "utf8");
    for (const specifier of relativeImports(source)) {
      const dependency = path.resolve(path.dirname(modulePath), specifier);
      assert.ok(dependency.startsWith(`${root}${path.sep}`), `${specifier} escapes the package root`);
      await readFile(dependency, "utf8");
      pending.push(dependency);
    }
  }
}

test("package contains local Markdown assets and excludes node_modules", async () => {
  const entries = await listArchiveEntries();

  for (const required of [
    "markdown.js",
    "vendor/marked.esm.js",
    "vendor/purify.es.mjs",
    "vendor/THIRD_PARTY_NOTICES.md",
  ]) {
    assert.ok(entries.includes(required), `package is missing ${required}`);
  }
  assert.equal(entries.some((entry) => entry.includes("node_modules")), false);
});

test("package runtime contains no CDN references", async () => {
  const entries = await listArchiveEntries();
  await withExtractedArchive(async (root) => {
    const runtimeSources = await Promise.all(
      entries
        .filter((entry) => /\.(?:html|js|mjs)$/.test(entry))
        .map((entry) => readFile(path.join(root, entry), "utf8"))
    );
    assert.doesNotMatch(
      runtimeSources.join("\n"),
      /https?:\/\/(?:cdn\.|unpkg\.com|cdn\.jsdelivr\.net)/i
    );
  });
});

test("every Side Panel module import resolves inside the package", async () => {
  await withExtractedArchive(async (root) => {
    await assertSidePanelImportsResolve(root);
  });
});
