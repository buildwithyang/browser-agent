# Frontend French Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add complete French localization to the React frontend with automatic detection, persistent selection, a three-language selector, and French date formatting.

**Architecture:** Extend the existing context-based i18n system rather than adding a dependency. Move language metadata and pure detection/lookup behavior into exported helpers so they can be unit tested, then keep the provider responsible for DOM synchronization and persistence. Add a full `fr` dictionary matching the English schema.

**Tech Stack:** React 18, Vite 5, Vitest, plain CSS.

## Global Constraints

- Supported frontend languages are exactly `zh`, `en`, and `fr`.
- The Chrome extension, Gateway, AI output language, and `privacy.html` are out of scope.
- Saved language takes priority over browser language; unsupported browser languages fall back to English.
- French copy falls back to English, then Chinese, then the translation key.
- The selector uses a native `<select>` and preserves the current dark industrial visual style.
- Update `frontend/README.md` and keep this plan under `docs/superpowers`.

---

### Task 1: Testable Language Core and Selector

**Files:**
- Create: `frontend/src/i18n.test.jsx`
- Modify: `frontend/src/i18n.jsx`

**Interfaces:**
- Produces: `LANGUAGES`, `detectLang(storage, browserLanguages)`, `resolveMessage(lang, key)`, and `LanguageToggle`.

- [ ] **Step 1: Write failing tests**

Add Vitest tests that assert saved-language priority, `fr-FR`/`fr-CA` detection, English fallback, French-to-English message fallback, and three selector options.

- [ ] **Step 2: Run tests to verify failure**

Run: `cd frontend && npm test -- src/i18n.test.jsx`

Expected: FAIL because the new exports and French option do not exist.

- [ ] **Step 3: Implement the language core**

Define metadata for `zh`, `en`, `fr`; detect against `navigator.languages`; synchronize HTML language; persist selection; replace the binary button with an accessible native select.

- [ ] **Step 4: Run focused tests**

Run: `cd frontend && npm test -- src/i18n.test.jsx`

Expected: PASS.

### Task 2: French Copy and Locale-Aware Dates

**Files:**
- Modify: `frontend/src/strings.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/i18n.test.jsx`

**Interfaces:**
- Consumes: `LANGUAGES.fr.locale === "fr-FR"`.
- Produces: complete `messages.fr` matching the English dictionary structure.

- [ ] **Step 1: Add a failing dictionary parity test**

Flatten the dictionaries in the test and assert French has the same leaf paths and array shapes as English.

- [ ] **Step 2: Run the parity test to verify failure**

Run: `cd frontend && npm test -- src/i18n.test.jsx`

Expected: FAIL because `messages.fr` is missing.

- [ ] **Step 3: Add all French user-facing copy**

Translate navigation, landing page, résumé management, and extension-connection card copy into France French, using `CV` consistently.

- [ ] **Step 4: Use language metadata for dates**

Replace the binary Chinese/English locale branch in `App.jsx` with the locale exported by the i18n context.

- [ ] **Step 5: Run focused tests**

Run: `cd frontend && npm test -- src/i18n.test.jsx`

Expected: PASS.

### Task 3: Visual Integration and Documentation

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/README.md`

**Interfaces:**
- Consumes: `.lang-select` emitted by `LanguageToggle`.

- [ ] **Step 1: Style the language selector**

Keep the compact bordered control, add clear focus-visible state, and ensure it fits the mobile navigation without hiding the primary CTA.

- [ ] **Step 2: Document localization scope**

Add a frontend README section describing automatic detection, local persistence, supported languages, and exclusions.

- [ ] **Step 3: Run the full frontend verification**

Run: `cd frontend && npm test`

Expected: all Vitest tests pass.

Run: `cd frontend && npm run build`

Expected: Vite production build succeeds.

- [ ] **Step 4: Review the final diff**

Run: `git diff --check` and confirm only the planned frontend files and `docs/superpowers` plan changed.
