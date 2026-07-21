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
const REMOTE_MODULE_SPECIFIER_PATTERN = /^https?:\/\//i;
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

/** Return static and literal dynamic module specifiers in source order. */
function moduleSpecifiers(source) {
  const staticPattern =
    /(?:import|export)\s+(?:[^\n;"'`()]*?\s+from\s+)?(["'])([^"'`]+)\1/g;
  const dynamicPattern = /import\s*\(\s*(["'`])([^"'`]+)\1\s*\)/g;
  const matches = [];

  for (const match of source.matchAll(staticPattern)) {
    matches.push({ index: match.index, specifier: match[2] });
  }
  for (const match of source.matchAll(dynamicPattern)) {
    if (match[1] === "`" && match[2].includes("${")) continue;
    matches.push({ index: match.index, specifier: match[2] });
  }

  matches.sort((left, right) => left.index - right.index);
  return matches.map((match) => match.specifier);
}

/** Return relative module specifiers that must resolve inside the package. */
function relativeImports(source) {
  return moduleSpecifiers(source).filter((specifier) => specifier.startsWith("."));
}

/** Identify HTTP(S) module imports without inspecting unrelated URL strings. */
function containsRemoteModuleImport(source) {
  for (const specifier of moduleSpecifiers(source)) {
    if (REMOTE_MODULE_SPECIFIER_PATTERN.test(specifier)) return true;
  }
  return false;
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

/** Require the strict NDJSON parser in every production Extension archive. */
test("production package contains Workspace streaming runtime", async () => {
  const entries = await listArchiveEntries();

  assert.ok(entries.includes("workspace-stream.js"));
});

test("production package publishes Extension 0.3.0 on protocol v4 without Action fields", async () => {
  await withExtractedArchive(async (root) => {
    const [manifestSource, configSource, backgroundSource] = await Promise.all([
      readFile(path.join(root, "manifest.json"), "utf8"),
      readFile(path.join(root, "config.js"), "utf8"),
      readFile(path.join(root, "background.js"), "utf8"),
    ]);
    const manifest = JSON.parse(manifestSource);
    const protocolMatch = configSource.match(
      /EXTENSION_PROTOCOL_VERSION\s*=\s*(\d+)/
    );

    assert.equal(manifest.version, "0.3.0");
    assert.ok(protocolMatch, "config.js must publish EXTENSION_PROTOCOL_VERSION");
    assert.equal(Number(protocolMatch[1]), 4);
    assert.doesNotMatch(backgroundSource, /quick_insight_action|selectedActionId/);
  });
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

test("package contains the local DM Sans font and license", async () => {
  const entries = await listArchiveEntries();
  assert.ok(entries.includes("fonts/dm-sans-latin-variable.woff2"));
  assert.ok(entries.includes("fonts/LICENSE.DM-Sans-OFL.txt"));

  await withExtractedArchive(async (root) => {
    const license = await readFile(
      path.join(root, "fonts/LICENSE.DM-Sans-OFL.txt"),
      "utf8"
    );
    assert.match(license, /SIL OPEN FONT LICENSE Version 1\.1/);
  });
});

test("package runtime contains no remote module or stylesheet imports", async () => {
  const entries = await listArchiveEntries();
  await withExtractedArchive(async (root) => {
    for (const entry of entries.filter((candidate) => /\.(?:css|js|mjs)$/.test(candidate))) {
      const source = await readFile(path.join(root, entry), "utf8");
      if (entry.endsWith(".css")) {
        assert.doesNotMatch(source, REMOTE_CSS_IMPORT_PATTERN, `${entry} imports a remote CSS file`);
      } else {
        assert.equal(containsRemoteModuleImport(source), false, `${entry} imports a remote module`);
      }
    }
  });
});

test("remote dependency policy rejects HTTP imports and CSS imports without blocking product URLs", () => {
  for (const source of [
    'import "https://modules.example.com/runtime.js";',
    'const development = import("http://127.0.0.1/runtime.js");',
    'const template = import(`https://modules.example.com/template.js`);',
    'export { runtime } from "https://modules.example.com/export.js";',
  ]) {
    assert.equal(containsRemoteModuleImport(source), true);
  }
  assert.match('@import url("https://example.com/theme.css");', REMOTE_CSS_IMPORT_PATTERN);

  for (const source of [
    'const STORE_URL = "https://chromewebstore.google.com/detail/agent-bridge/id";',
    'const API_URL = "https://browser.buildwithyang.com/api/tasks/workspace";',
  ]) {
    assert.equal(containsRemoteModuleImport(source), false);
  }
});

test("import scanner recognizes static, exported, and dynamic relative modules", () => {
  const source = [
    'import value from "./static.js";',
    'const lazy = import("./lazy.js");',
    'const template = import(`./template.js`);',
    'const computed = import(`./${name}.js`);',
    'export { other } from "./other.js";',
  ].join("\n");

  assert.deepEqual(relativeImports(source), [
    "./static.js",
    "./lazy.js",
    "./template.js",
    "./other.js",
  ]);
});

test("every Side Panel module import resolves inside the package", async () => {
  await withExtractedArchive(async (root) => {
    await assertSidePanelImportsResolve(root);
  });
});
