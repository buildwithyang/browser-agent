import { test } from "node:test";
import assert from "node:assert/strict";

import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);
const ZIP_PATH = new URL("../dist/agent-bridge-extension.zip", import.meta.url);
const EXTENSION_ROOT = fileURLToPath(new URL("../", import.meta.url));
const MODULE_CDN_PATTERN =
  /https?:\/\/(?:cdn\.|unpkg\.com|cdn\.jsdelivr\.net|esm\.sh|cdnjs\.cloudflare\.com|cdn\.skypack\.dev)/i;
const REMOTE_CSS_IMPORT_PATTERN =
  /@import\s+(?:url\(\s*)?["']?\s*https?:\/\//i;
const LICENSE_ASSETS = [
  {
    packaged: "vendor/LICENSE.marked.txt",
    installed: "node_modules/marked/LICENSE",
  },
  {
    packaged: "vendor/LICENSE.dompurify-Apache-2.0.txt",
    installed: "node_modules/dompurify/LICENSE",
  },
];

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

/** Return static and dynamic relative imports declared by one JavaScript module. */
function relativeImports(source) {
  const importPattern =
    /(?:(?:import|export)\s+(?:[^"'()]*?\s+from\s+)?["'](\.[^"']+)["']|import\s*\(\s*["'](\.[^"']+)["'])/g;
  return [...source.matchAll(importPattern)].map((match) => match[1] || match[2]);
}

/** Identify external runtime dependencies while allowing normal product URLs. */
function containsRemoteRuntimeDependency(source) {
  return MODULE_CDN_PATTERN.test(source) || REMOTE_CSS_IMPORT_PATTERN.test(source);
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
    "vendor/LICENSE.marked.txt",
    "vendor/LICENSE.dompurify-Apache-2.0.txt",
    "vendor/THIRD_PARTY_NOTICES.md",
  ]) {
    assert.ok(entries.includes(required), `package is missing ${required}`);
  }
  assert.equal(entries.some((entry) => entry.includes("node_modules")), false);
});

test("package contains complete licenses copied from locked dependencies", async () => {
  await withExtractedArchive(async (root) => {
    for (const license of LICENSE_ASSETS) {
      const [packaged, installed] = await Promise.all([
        readFile(path.join(root, license.packaged)),
        readFile(path.join(EXTENSION_ROOT, license.installed)),
      ]);
      assert.deepEqual(packaged, installed, `${license.packaged} must be byte-identical`);
    }
  });
});

test("package runtime contains no CDN references", async () => {
  const entries = await listArchiveEntries();
  await withExtractedArchive(async (root) => {
    const runtimeSources = await Promise.all(
      entries
        .filter((entry) => /\.(?:css|html|js|mjs)$/.test(entry))
        .map((entry) => readFile(path.join(root, entry), "utf8"))
    );
    assert.equal(containsRemoteRuntimeDependency(runtimeSources.join("\n")), false);
  });
});

test("remote dependency policy covers ESM CDNs and CSS imports without blocking product URLs", () => {
  for (const source of [
    'import "https://esm.sh/marked";',
    'import "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.4.12/purify.es.mjs";',
    'import "https://cdn.skypack.dev/marked";',
    '@import url("https://example.com/theme.css");',
  ]) {
    assert.equal(containsRemoteRuntimeDependency(source), true);
  }

  for (const source of [
    "https://chromewebstore.google.com/detail/agent-bridge/id",
    "https://browser.buildwithyang.com/api/tasks/workspace",
  ]) {
    assert.equal(containsRemoteRuntimeDependency(source), false);
  }
});

test("import scanner recognizes static, exported, and dynamic relative modules", () => {
  const source = [
    'import value from "./static.js";',
    'const lazy = import("./lazy.js");',
    'export { other } from "./other.js";',
  ].join("\n");

  assert.deepEqual(relativeImports(source), ["./static.js", "./lazy.js", "./other.js"]);
});

test("every Side Panel module import resolves inside the package", async () => {
  await withExtractedArchive(async (root) => {
    await assertSidePanelImportsResolve(root);
  });
});
