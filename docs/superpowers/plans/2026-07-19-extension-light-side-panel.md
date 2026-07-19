# Extension Light Side Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the industrial dark Shared Workspace with a responsive Chrome-native light Side Panel, render Quick Insight Actions as wrapping tags, and show resume results as a fixed website preview.

**Architecture:** Keep all gateway and Workspace contracts unchanged. Treat the extension as a presentation shell: `background.js` owns the isolated Quick Insight overlay styling, `sidepanel.js` derives a DOM-independent document presentation model, and `sidepanel.html`/`sidepanel.css` provide the responsive light layout.

**Tech Stack:** Chrome Extension Manifest V3, vanilla JavaScript ES modules, semantic HTML, CSS, Node.js built-in test runner.

## Global Constraints

- Read and preserve the current behavior documented in `extension/README.md`.
- Do not modify gateway APIs, `DocumentContent`, Workspace persistence, Action routing, shared histories, or the ten-message limit.
- Support Side Panel widths from 280px through 600px without page-level horizontal scrolling.
- Use Chrome-native light colors and system UI fonts; do not add dependencies or remote fonts.
- Keep the Quick Insight overlay dark; only its Actions become wrapping pill tags.
- Resume documents open the fixed prototype URL `https://browser.buildwithyang.com`; Cover Letter and other documents stay inline and copyable.
- Every new exported constant/function and every new rendering helper must include a concise responsibility comment.
- Follow red-green-refactor: every production change starts with a test that is observed failing for the intended reason.

---

### Task 1: Quick Insight wrapping Action tags

**Files:**
- Modify: `extension/quick-insight.test.js`
- Modify: `extension/background.js:673-711, 860-865`

**Interfaces:**
- Consumes: the existing `renderActions(container, actionList)` behavior and `.ab-actions` / `.ab-action` Shadow DOM classes.
- Produces: the same Action click messages and error behavior, presented by a wrapping tag layout.

- [ ] **Step 1: Write the failing Action layout test**

Append this test to `extension/quick-insight.test.js`:

```js
test("Quick Insight actions use wrapping content-width tags", async () => {
  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  assert.match(
    source,
    /\.ab-actions\s*\{[^}]*display:\s*flex;[^}]*flex-wrap:\s*wrap;/s
  );
  assert.doesNotMatch(
    source,
    /\.ab-actions\s*\{[^}]*flex-direction:\s*column;/s
  );
  assert.match(source, /\.ab-action\s*\{[^}]*border-radius:\s*999px;/s);
  assert.match(source, /\.ab-action-err:empty\s*\{[^}]*display:\s*none;/s);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd extension && node --test quick-insight.test.js`

Expected: FAIL because `.ab-actions` still declares `flex-direction: column` and `.ab-action` still uses an 8px radius.

- [ ] **Step 3: Implement the minimal wrapping tag styles**

Replace the Quick Insight Action CSS embedded in `extension/background.js` with:

```css
.ab-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}
.ab-action {
  display: inline-flex;
  width: auto;
  min-height: 32px;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  border: 1px solid var(--signal);
  border-radius: 999px;
  color: var(--signal);
  background: var(--signal-soft);
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.25;
}
.ab-action:hover { filter: brightness(1.12); }
.ab-action:disabled { opacity: .6; cursor: default; }
.ab-action-err:empty { display: none; }
.ab-action-err:not(:empty) {
  flex: 0 0 100%;
  color: var(--alert);
  font-size: 12.5px;
}
```

Do not change `renderActions()` request payloads or event handlers.

- [ ] **Step 4: Run focused and full extension tests**

Run: `cd extension && node --test quick-insight.test.js`

Expected: PASS.

Run: `cd extension && npm test`

Expected: all tests PASS.

- [ ] **Step 5: Commit the Quick Insight presentation change**

```bash
git add extension/quick-insight.test.js extension/background.js
git commit -m "style: wrap quick insight actions"
```

---

### Task 2: Resume website-preview presentation

**Files:**
- Modify: `extension/sidepanel.test.js`
- Modify: `extension/sidepanel.js:4-101, 185-213`

**Interfaces:**
- Consumes: `WorkspaceState.currentDocument` with the existing `{kind, title, text, html}` fields.
- Produces: exported `CV_PREVIEW_URL: string`, exported `documentPresentation(documentState): object | null`, and `workspaceView().document.presentation` equal to `"resume-preview"` or `"inline"`.

- [ ] **Step 1: Write failing document-presentation tests**

Add these tests to `extension/sidepanel.test.js`:

```js
test("resume documents become a fixed website preview", () => {
  const view = workspaceView({
    actions: [{ id: "tailor_resume", title: "Tailor resume" }],
    currentDocument: {
      kind: "resume",
      title: "Tailored resume",
      text: "private resume body",
      html: "<article>private resume body</article>",
    },
  }, "en");

  assert.equal(sidepanel.CV_PREVIEW_URL, "https://browser.buildwithyang.com");
  assert.equal(view.document.presentation, "resume-preview");
  assert.equal(view.document.previewUrl, sidepanel.CV_PREVIEW_URL);
});

test("cover letter documents remain inline and copyable", () => {
  const view = workspaceView({
    actions: [{ id: "write_cover_letter", title: "Write cover letter" }],
    currentDocument: {
      kind: "cover_letter",
      title: "Cover Letter",
      text: "Dear Hiring Manager",
    },
  }, "en");

  assert.equal(view.document.presentation, "inline");
  assert.equal(view.document.previewUrl, null);
  assert.equal(view.document.text, "Dear Hiring Manager");
});

test("resume preview links open safely in a new tab", async () => {
  const source = await readFile(new URL("./sidepanel.js", import.meta.url), "utf8");
  assert.match(source, /previewLink\.target\s*=\s*"_blank"/);
  assert.match(source, /previewLink\.rel\s*=\s*"noopener noreferrer"/);
});
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd extension && node --test sidepanel.test.js`

Expected: FAIL because `CV_PREVIEW_URL`, `presentation`, `previewUrl`, and the safe preview link do not exist.

- [ ] **Step 3: Add the pure document presentation model**

Add this public constant and function near the Side Panel message constants:

```js
export const CV_PREVIEW_URL = "https://browser.buildwithyang.com";

/** Convert a Workspace document into the presentation contract used by the Side Panel. */
export function documentPresentation(documentState) {
  if (!documentState || typeof documentState !== "object") return null;
  const isResume = documentState.kind === "resume";
  return {
    ...documentState,
    presentation: isResume ? "resume-preview" : "inline",
    previewUrl: isResume ? CV_PREVIEW_URL : null,
  };
}
```

In `workspaceView()`, replace the raw document assignment with:

```js
document: documentPresentation(state.currentDocument),
```

Add localized copy:

```js
// en
resumePreview: "CV website preview",
resumePreviewHint: "Open the current tailored CV in a full browser tab.",
openResumePreview: "Open CV preview",

// zh
resumePreview: "CV 网页预览",
resumePreviewHint: "在完整浏览器标签页中查看当前定制 CV。",
openResumePreview: "打开 CV 预览",
```

- [ ] **Step 4: Branch resume rendering away from inline document rendering**

Add this focused helper before `renderDocument()`:

```js
/** Render a resume as a safe link to the current prototype website preview. */
function renderResumePreview(container, view) {
  const card = document.createElement("article");
  card.className = "resume-preview-card";
  const copy = document.createElement("div");
  copy.className = "resume-preview-copy";
  copy.append(
    textElement("span", "artifact-kind", view.strings.resumePreview),
    textElement("h2", "", view.document.title || view.strings.resumePreview),
    textElement("p", "", view.strings.resumePreviewHint)
  );
  const previewLink = textElement("a", "resume-preview-link", view.strings.openResumePreview);
  previewLink.href = view.document.previewUrl;
  previewLink.target = "_blank";
  previewLink.rel = "noopener noreferrer";
  copy.append(previewLink);
  card.append(copy);
  container.append(card);
}
```

Start `renderDocument()` with:

```js
if (!view.document) return;
if (view.document.presentation === "resume-preview") {
  renderResumePreview(container, view);
  return;
}
```

Keep the existing inline card and copy behavior for other document kinds.

- [ ] **Step 5: Run focused and full extension tests**

Run: `cd extension && node --test sidepanel.test.js`

Expected: PASS.

Run: `cd extension && npm test`

Expected: all tests PASS.

- [ ] **Step 6: Commit the resume presentation branch**

```bash
git add extension/sidepanel.test.js extension/sidepanel.js
git commit -m "feat: preview tailored resumes on the web"
```

---

### Task 3: Chrome-native light responsive Side Panel

**Files:**
- Modify: `extension/sidepanel.test.js`
- Modify: `extension/sidepanel.html:10-60`
- Modify: `extension/sidepanel.js:164-183, 215-236`
- Modify: `extension/sidepanel.css`

**Interfaces:**
- Consumes: the existing stable element IDs resolved by `sidePanelElements()` and the document presentation produced by Task 2.
- Produces: a three-row responsive shell (`header`, scrollable timeline, sticky composer) with no page-level horizontal overflow.

- [ ] **Step 1: Write failing structure and responsive-style tests**

Add this test to `extension/sidepanel.test.js`:

```js
test("Side Panel uses a light responsive shell without industrial decoration", async () => {
  const [html, css, source] = await Promise.all([
    readFile(new URL("./sidepanel.html", import.meta.url), "utf8"),
    readFile(new URL("./sidepanel.css", import.meta.url), "utf8"),
    readFile(new URL("./sidepanel.js", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(html, /brand-mark|signal-rule/);
  assert.doesNotMatch(source, /message-index|empty-index/);
  assert.match(css, /color-scheme:\s*light/);
  assert.match(css, /grid-template-rows:\s*auto minmax\(0,\s*1fr\) auto/);
  assert.match(css, /html,\s*body\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.workspace-header h1\s*\{[^}]*-webkit-line-clamp:\s*2/s);
  assert.match(css, /\.action-chip\s*\{[^}]*border-radius:\s*999px/s);
  assert.match(css, /\.message-content\s*\{[^}]*overflow-wrap:\s*anywhere/s);
});
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd extension && node --test sidepanel.test.js`

Expected: FAIL because the HTML still contains `brand-mark`/`signal-rule`, the root is dark, and the title is single-line.

- [ ] **Step 3: Simplify the semantic Side Panel shell**

Replace the internal header and remove the signal rule in `sidepanel.html`:

```html
<header class="workspace-header">
  <div class="workspace-title-row">
    <h1 id="workspace-title">Shared Workspace</h1>
    <span id="connection-status" class="connection-status">Standby</span>
  </div>
  <a id="source-link" class="source-link" href="#" target="_blank" rel="noopener noreferrer">
    <span id="source-host">No active page</span>
    <span aria-hidden="true">↗</span>
  </a>
</header>
```

Change the textarea to `rows="2"`. Keep every existing ID used by `sidePanelElements()`.

- [ ] **Step 4: Simplify message and empty-state markup**

In `renderHistories()`, remove the message number and render only the role and content:

```js
/** Render the single chronological shared history without grouping by Action. */
function renderHistories(container, view) {
  view.histories.forEach((history) => {
    const message = document.createElement("article");
    message.className = `message ${history.role === "user" ? "user" : "assistant"}`;
    const body = document.createElement("div");
    body.className = "message-body";
    body.append(
      textElement(
        "span",
        "message-role",
        history.role === "user" ? view.strings.user : view.strings.assistant
      ),
      textElement("p", "message-content", history.content)
    );
    message.append(body);
    container.append(message);
  });
}
```

For the disconnected state, omit the numeric `empty-index` and keep only its heading and explanation.

- [ ] **Step 5: Replace dark CSS with the light responsive system**

Replace `extension/sidepanel.css` with this complete stylesheet:

```css
:root {
  color-scheme: light;
  --page: #f6f8fa;
  --surface: #ffffff;
  --surface-subtle: #f8f9fa;
  --border: #dfe3e8;
  --border-strong: #c7cdd4;
  --text: #202124;
  --muted: #687078;
  --primary: #1a73e8;
  --primary-soft: #e8f0fe;
  --danger: #c5221f;
  --success: #188038;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "PingFang SC", "Microsoft YaHei", sans-serif;
}

* {
  box-sizing: border-box;
  min-width: 0;
}

html,
body {
  width: 100%;
  height: 100%;
  margin: 0;
  overflow-x: hidden;
}

body {
  color: var(--text);
  background: var(--page);
  font: 14px/1.5 var(--font);
}

button,
textarea {
  font: inherit;
}

button,
a,
textarea {
  -webkit-tap-highlight-color: transparent;
}

.workspace-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  width: 100%;
  height: 100dvh;
  min-width: 280px;
}

.workspace-header {
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.workspace-title-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.workspace-header h1 {
  display: -webkit-box;
  flex: 1;
  margin: 0;
  overflow: hidden;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.3;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.connection-status {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
  white-space: nowrap;
}

.connection-status::before {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  content: "";
}

.connection-status.ready {
  color: var(--success);
}

.connection-status.busy {
  color: var(--primary);
}

.source-link {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 5px;
  margin-top: 5px;
  overflow: hidden;
  color: var(--muted);
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
}

#source-host {
  overflow: hidden;
  text-overflow: ellipsis;
}

.source-link:hover {
  color: var(--primary);
}

.source-link:focus-visible,
button:focus-visible,
textarea:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.timeline {
  min-height: 0;
  padding: 14px 16px 24px;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.empty-state {
  display: grid;
  min-height: 100%;
  place-content: center;
  padding: 28px 16px;
  text-align: center;
}

.empty-state h2 {
  margin: 0 0 5px;
  font-size: 18px;
}

.empty-state p {
  max-width: 300px;
  margin: 0;
  color: var(--muted);
}

.timeline-empty-note {
  margin: 10px 0 18px;
  color: var(--muted);
  font-size: 13px;
}

.insight-card,
.artifact-card,
.resume-preview-card {
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.08);
}

.insight-card {
  padding: 12px 13px;
}

.insight-label,
.artifact-kind,
.message-role,
.turn-meter {
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
}

.insight-card h2 {
  margin: 4px 0 0;
  font-size: 16px;
  font-weight: 600;
}

.insight-score {
  float: right;
  margin-left: 10px;
  color: var(--primary);
  font-size: 22px;
  line-height: 1;
}

.message {
  display: flex;
  margin: 0 0 14px;
}

.message.user {
  justify-content: flex-end;
}

.message-body {
  max-width: min(88%, 560px);
}

.message.user .message-body {
  padding: 9px 11px;
  border-radius: 14px 14px 4px 14px;
  background: var(--primary-soft);
}

.message-role {
  display: block;
  margin-bottom: 3px;
}

.message.user .message-role {
  color: var(--primary);
}

.message-content {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.artifact-card {
  margin-top: 20px;
}

.artifact-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 13px 10px;
  border-bottom: 1px solid var(--border);
}

.artifact-head h2,
.resume-preview-copy h2 {
  margin: 3px 0 0;
  font-size: 16px;
  font-weight: 600;
}

.artifact-copy {
  flex: 0 0 auto;
  padding: 6px 9px;
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  color: var(--primary);
  background: var(--surface);
  cursor: pointer;
  font-size: 12px;
}

.artifact-body {
  max-height: 320px;
  padding: 13px;
  overflow: auto;
  overflow-wrap: anywhere;
}

.artifact-body > :first-child {
  margin-top: 0;
}

.artifact-body > :last-child {
  margin-bottom: 0;
}

.artifact-body pre {
  max-width: 100%;
  overflow: auto;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-subtle);
}

.resume-preview-card {
  margin-top: 20px;
  padding: 14px;
}

.resume-preview-copy p {
  margin: 6px 0 12px;
  color: var(--muted);
}

.resume-preview-link {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  padding: 6px 12px;
  border-radius: 8px;
  color: #ffffff;
  background: var(--primary);
  font-weight: 600;
  text-decoration: none;
}

.resume-preview-link:hover {
  background: #1765cc;
}

.composer {
  position: relative;
  z-index: 2;
  padding: 11px 14px 13px;
  border-top: 1px solid var(--border);
  background: var(--surface);
  box-shadow: 0 -4px 12px rgba(60, 64, 67, 0.08);
}

.composer-heading,
.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.composer-heading label {
  font-size: 13px;
  font-weight: 600;
}

.action-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin: 9px 0 10px;
}

.action-chip {
  width: auto;
  min-height: 30px;
  padding: 5px 11px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  color: var(--text);
  background: var(--surface);
  cursor: pointer;
  font-size: 12px;
  line-height: 1.25;
}

.action-chip:hover:not(:disabled) {
  border-color: var(--primary);
}

.action-chip[aria-pressed="true"] {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-soft);
}

.action-chip:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

textarea {
  display: block;
  width: 100%;
  min-height: 60px;
  max-height: 144px;
  resize: vertical;
  padding: 9px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  color: var(--text);
  background: var(--surface);
  caret-color: var(--primary);
}

textarea::placeholder {
  color: #8a9199;
}

textarea:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.composer-error {
  margin-top: 7px;
  color: var(--danger);
  font-size: 12px;
}

.composer-footer {
  margin-top: 9px;
}

.composer-hint {
  max-width: 70%;
  color: var(--muted);
  font-size: 11px;
}

#send-button {
  display: inline-flex;
  flex: 0 0 auto;
  min-height: 34px;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px solid var(--primary);
  border-radius: 8px;
  color: #ffffff;
  background: var(--primary);
  cursor: pointer;
  font-weight: 600;
}

#send-button:hover:not(:disabled) {
  background: #1765cc;
}

#send-button:disabled {
  border-color: var(--border);
  color: #8a9199;
  background: #eef0f2;
  cursor: not-allowed;
}

@media (max-width: 359px) {
  .workspace-header,
  .timeline {
    padding-right: 12px;
    padding-left: 12px;
  }

  .composer {
    padding-right: 12px;
    padding-left: 12px;
  }

  .action-chip {
    padding: 5px 9px;
    font-size: 11px;
  }

  .composer-hint {
    max-width: 58%;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 6: Run focused and full extension tests**

Run: `cd extension && node --test sidepanel.test.js`

Expected: PASS.

Run: `cd extension && npm test`

Expected: all tests PASS.

- [ ] **Step 7: Commit the responsive light layout**

```bash
git add extension/sidepanel.test.js extension/sidepanel.html extension/sidepanel.js extension/sidepanel.css
git commit -m "style: redesign shared workspace panel"
```

---

### Task 4: User documentation and release verification

**Files:**
- Modify: `extension/README.md`

**Interfaces:**
- Consumes: the completed Quick Insight tags, light Side Panel, and fixed CV preview behavior.
- Produces: user-facing documentation that accurately describes the current source implementation and prototype limitation.

- [ ] **Step 1: Update current UI behavior in the extension README**

In the interaction and Workspace sections, document these exact facts:

```markdown
- Quick Insight 中的 Actions 使用紧凑标签并按面板宽度自动换行。
- Side Panel 使用浅色响应式布局；Chrome 不提供扩展设置默认宽度的 API，用户可自行拖动面板边界。
- `resume` 结果当前显示网页预览入口，原型阶段固定打开 `https://browser.buildwithyang.com`；Cover Letter 等其他文档仍在 Side Panel 内显示并可复制。
```

Do not describe the fixed URL as a production CV hosting implementation.

- [ ] **Step 2: Run complete extension verification**

Run: `cd extension && npm test`

Expected: all tests PASS with no failures.

Run: `cd extension && npm run test:package`

Expected: package creation succeeds and the archive contains `sidepanel.html`, `sidepanel.css`, and `sidepanel.js`.

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 3: Manually verify the extension at narrow and wide widths**

Reload the unpacked `extension/` directory in `chrome://extensions`, open a LinkedIn or Indeed Quick Insight, and verify:

1. Four Quick Insight Actions share rows and wrap instead of becoming four full-width buttons.
2. Side Panel remains usable at approximately 280px and 600px widths.
3. A long job title clamps to two lines.
4. Empty history does not create a large outlined placeholder.
5. Actions wrap above the composer without horizontal scrolling.
6. A resume result shows the website-preview button and does not expose the inline resume body.
7. A Cover Letter result still shows inline content and copy control.

- [ ] **Step 4: Commit documentation**

```bash
git add extension/README.md
git commit -m "docs: describe light extension workspace"
```
