# Quiet Precision Side Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current warm, card-heavy Chrome Side Panel with the approved Quiet Precision layout while preserving every Workspace behavior and protocol contract.

**Architecture:** Keep the existing header/timeline/composer three-row grid and stable DOM ids. Add one local font asset boundary, one structured timeline-notice renderer, and one `input-shell` wrapper; all Workspace lifecycle, Markdown, Attachment, Action, retry, and persistence logic remains unchanged.

**Tech Stack:** Chrome Extension Manifest V3, semantic HTML, CSS, vanilla ES modules, Node test runner, JSDOM, shell zip packaging.

## Global Constraints

- Implement [the approved design spec](../specs/2026-07-20-quiet-precision-side-panel-design.md) exactly.
- Support Side Panel widths from 280px through 600px without page-level horizontal scrolling.
- Keep protocol v2, Workspace schema, stable DOM ids, histories, Artifacts, Attachments, Actions, retry behavior, and the 10-message limit unchanged.
- Keep Assistant and Cover Letter Markdown sanitized through the existing Marked + DOMPurify boundary; User Messages remain text-only.
- Bundle DM Sans locally; runtime CSS must not use a remote `@import` or remote font URL.
- Use test-first red/green cycles for every production-code change.

---

### Task 1: Vendor DM Sans and enforce the package boundary

**Files:**
- Create: `extension/fonts/dm-sans-latin-variable.woff2`
- Create: `extension/fonts/LICENSE.DM-Sans-OFL.txt`
- Modify: `extension/package.sh`
- Modify: `extension/scripts/verify-package.mjs`

**Interfaces:**
- Consumes: the existing explicit `FILES` package whitelist and `dist/agent-bridge-extension.zip`.
- Produces: packaged entries `fonts/dm-sans-latin-variable.woff2` and `fonts/LICENSE.DM-Sans-OFL.txt` for `sidepanel.css`.

- [ ] **Step 1: Write the failing package tests**

Add required archive entries to `verify-package.mjs` and verify that the license is present and identifies the SIL Open Font License:

```js
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
```

- [ ] **Step 2: Run the package test and verify RED**

Run: `cd extension && npm run test:package`

Expected: FAIL because both `fonts/` archive entries are absent.

- [ ] **Step 3: Add the official font assets and package whitelist**

Create `extension/fonts/`, download the official Latin variable WOFF2 selected by the Google Fonts family CSS, and copy the official Google Fonts OFL license:

```bash
mkdir -p extension/fonts
curl -fsSL 'https://fonts.gstatic.com/s/dmsans/v17/rP2Hp2ywxg089UriCZOIHTWEBlw.woff2' \
  -o extension/fonts/dm-sans-latin-variable.woff2
curl -fsSL 'https://raw.githubusercontent.com/google/fonts/main/ofl/dmsans/OFL.txt' \
  -o extension/fonts/LICENSE.DM-Sans-OFL.txt
```

Add `fonts` to the exact `FILES` array in `package.sh`:

```bash
FILES=(
  manifest.json
  background.js
  quick-insight.js
  workspace-operation.js
  workspace.js
  workspace-controller.js
  markdown.js
  vendor
  content.js
  sidepanel.html
  sidepanel.css
  sidepanel.js
  popup.html
  popup.js
  auth.js
  config.js
  icons
  fonts
)
```

Do not add a runtime dependency or remote font request.

- [ ] **Step 4: Run the package test and verify GREEN**

Run: `cd extension && npm run test:package`

Expected: PASS, with both font entries listed in the generated zip.

- [ ] **Step 5: Commit the font package boundary**

```bash
git add extension/fonts extension/package.sh extension/scripts/verify-package.mjs
git commit -m "build: package local side panel font"
```

### Task 2: Add structured empty states and the integrated composer shell

**Files:**
- Modify: `extension/sidepanel.html`
- Modify: `extension/sidepanel.js`
- Modify: `extension/sidepanel.test.js`

**Interfaces:**
- Consumes: `renderSidePanel(documentRef, model, dependencies)` and the stable element ids returned by `sidePanelElements()`.
- Produces: `.timeline-empty-state[data-state]` for `connected-empty`, `disconnected`, and `loading`; `.input-shell` containing `#message-input` and `#send-button`.

- [ ] **Step 1: Write failing DOM tests for the composer shell**

```js
test("composer integrates textarea and send button without changing stable ids", async () => {
  const { dom } = await renderState(workspace());
  const shell = dom.window.document.querySelector(".input-shell");

  assert.equal(shell?.querySelector("#message-input") !== null, true);
  assert.equal(shell?.querySelector("#send-button") !== null, true);
  assert.equal(dom.window.document.querySelectorAll("#message-input").length, 1);
  assert.equal(dom.window.document.querySelectorAll("#send-button").length, 1);
});
```

- [ ] **Step 2: Write failing DOM tests for all empty timeline states**

```js
test("timeline distinguishes connected empty, disconnected, and initial loading", async () => {
  const connected = await renderState(workspace());
  assert.equal(
    connected.dom.window.document.querySelector(".timeline-empty-state")?.dataset.state,
    "connected-empty"
  );
  assert.match(connected.dom.window.document.querySelector(".timeline")?.textContent || "", /Action/);

  const disconnected = await renderState(null);
  assert.equal(
    disconnected.dom.window.document.querySelector(".timeline-empty-state")?.dataset.state,
    "disconnected"
  );

  const loading = await renderState(null, { loading: true });
  assert.equal(
    loading.dom.window.document.querySelector(".timeline-empty-state")?.dataset.state,
    "loading"
  );
  assert.equal(loading.dom.window.document.querySelector(".timeline")?.getAttribute("aria-busy"), "true");
});
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `cd extension && node --test --test-name-pattern="composer integrates|timeline distinguishes" sidepanel.test.js`

Expected: FAIL because `.input-shell` and `.timeline-empty-state` do not exist.

- [ ] **Step 4: Implement the minimal semantic DOM**

Move the existing textarea and send button into one wrapper while keeping all ids and accessible labels:

```html
<div class="input-shell">
  <textarea id="message-input" rows="2" maxlength="10000"></textarea>
  <button id="send-button" type="submit" disabled>
    <span id="send-label">Send</span>
    <span aria-hidden="true">↑</span>
  </button>
</div>
```

Keep `.composer-footer` for `#composer-hint`. Add localized copy fields for connected empty, disconnected, and loading states. Render them through one internal helper:

```js
function timelineNotice(documentRef, state, icon, title, body) {
  const notice = documentRef.createElement("div");
  notice.className = "timeline-empty-state";
  notice.dataset.state = state;
  const mark = textElement(documentRef, "span", "timeline-empty-mark", icon);
  mark.setAttribute("aria-hidden", "true");
  notice.append(
    mark,
    textElement(documentRef, "strong", "timeline-empty-title", title),
    textElement(documentRef, "p", "timeline-empty-body", body)
  );
  return notice;
}
```

`renderTimeline()` selects `loading` only when `model.loading && !model.state`, `disconnected` when `!model.state`, and `connected-empty` when state exists without histories. It must not create a Message or Action.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run: `cd extension && node --test --test-name-pattern="composer integrates|timeline distinguishes" sidepanel.test.js`

Expected: both tests PASS.

- [ ] **Step 6: Run the complete Side Panel test file**

Run: `cd extension && node --test sidepanel.test.js`

Expected: all Side Panel tests PASS; lifecycle, retries, Markdown, Attachments, limits, and concurrency tests remain unchanged.

- [ ] **Step 7: Commit the structural UI change**

```bash
git add extension/sidepanel.html extension/sidepanel.js extension/sidepanel.test.js
git commit -m "feat: structure quiet side panel states"
```

### Task 3: Apply Quiet Precision styling and document the result

**Files:**
- Modify: `extension/sidepanel.css`
- Modify: `extension/sidepanel.test.js`
- Modify: `extension/README.md`

**Interfaces:**
- Consumes: Task 1 local font paths and Task 2 `.input-shell` / `.timeline-empty-state` DOM.
- Produces: the approved Quiet Precision visual system without changing JavaScript state or protocol behavior.

- [ ] **Step 1: Write failing CSS contract tests**

Extend the existing responsive CSS test with the essential design invariants:

```js
assert.match(css, /@font-face[\s\S]*DM Sans[\s\S]*fonts\/dm-sans-latin-variable\.woff2/);
assert.match(css, /--brand:\s*#604bd8/i);
assert.match(css, /--ink-soft:\s*#70727d/i);
assert.match(css, /\.timeline-empty-state\s*\{[^}]*place-items:\s*center/s);
assert.match(css, /\.input-shell\s*\{[^}]*position:\s*relative/s);
assert.match(css, /#send-button\s*\{[^}]*position:\s*absolute/s);
assert.match(css, /\.message\.assistant\s+\.message-surface\s*\{[^}]*border:\s*(?:0|none)/s);
assert.match(css, /\.action-chips\s*\{[^}]*flex-wrap:\s*wrap/s);
```

- [ ] **Step 2: Run the CSS test and verify RED**

Run: `cd extension && node --test --test-name-pattern="light responsive CSS" sidepanel.test.js`

Expected: FAIL on the first missing Quiet Precision token or selector.

- [ ] **Step 3: Implement the approved visual system**

Rewrite `sidepanel.css` around these exact rules:

- Add local `@font-face` for `DM Sans` weights 400–700 with `font-display: swap`.
- Use `#F7F8FB` canvas, `#FFFFFF` surface, `#1B1C25` ink, `#70727D` muted ink, `#E8E9EE` line, `#604BD8` brand, and `#F0EDFF` brand soft.
- Keep the three-row 100dvh grid and all existing overflow containment.
- Use a compact white Header with a two-line sans title and a soft-purple score pill.
- Center `.timeline-empty-state`; use a 42px soft-purple mark, concise title, and body.
- Remove border/background/shadow from Assistant message surfaces; retain the right-aligned soft-purple User bubble and all timestamps.
- Preserve local Markdown table/code scrolling; use a white bordered surface for tables and Artifact cards.
- Make Composer white with one subtle top divider; keep wrapped Action pills.
- Style `.input-shell` as the focused input surface and absolutely position the send button at its bottom-right without covering text.
- Keep `:focus-visible`, disabled/error/update states, `prefers-reduced-motion`, and the `max-width: 359px` compact layout.

- [ ] **Step 4: Run Side Panel tests and verify GREEN**

Run: `cd extension && node --test sidepanel.test.js`

Expected: all tests PASS.

- [ ] **Step 5: Update the user-facing Extension README**

Replace the existing generic light-layout sentence with a concise description of Quiet Precision: cool neutral canvas, brand-violet interaction states, flat Assistant messages, soft User bubbles, Artifact-only cards, centered empty states, and the integrated composer. Document that DM Sans is bundled locally and that no runtime font request is made.

- [ ] **Step 6: Run full Extension and package verification**

Run:

```bash
cd extension
npm test
npm run test:package
npm run package
```

Expected: all Node tests PASS; package verification PASS; generated archives contain the font and license; no remote runtime import is detected.

- [ ] **Step 7: Inspect the packaged Side Panel at representative widths**

Reload `extension/` from `chrome://extensions`, then inspect connected-empty, active conversation, Cover Letter Attachment, CV Attachment, retry error, and disabled-limit states at 280px, 400px, and 600px. Confirm no page-level horizontal overflow and that the composer remains usable.

- [ ] **Step 8: Commit the final visual implementation**

```bash
git add extension/sidepanel.css extension/sidepanel.test.js extension/README.md
git commit -m "style: apply quiet precision side panel"
```
