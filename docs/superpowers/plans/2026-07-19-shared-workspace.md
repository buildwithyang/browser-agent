# Shared Browser Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one locally persisted Workspace per authenticated user and normalized webpage resource, with backend-declared Actions and one shared conversation history.

**Architecture:** The gateway remains stateless: Context Router normalizes the resource URL, selects the Agent, validates each Workspace turn, and returns the complete next history. The MV3 extension owns Workspace persistence in `chrome.storage.local`; the Side Panel renders that state and sends commands through the background service worker.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest, Chrome MV3, vanilla JavaScript, Node test runner.

## Global Constraints

- Public Quick Insight and Workspace requests do not accept an `agent` selector.
- LinkedIn and Indeed Actions are `analyze`, `tailor_resume`, `write_cover_letter`, and `ask_more`; generic pages expose only `ask_more`.
- `len(histories) + 1 <= 10`, where `1` is the current user message.
- Workspace history is stored only in `chrome.storage.local`; no server Thread or DB tables are added.
- The backend returns the complete updated `histories`; the extension replaces local state instead of appending the assistant message itself.
- Page content update detection and cross-device synchronization are out of scope.

---

### Task 1: Gateway Workspace identity and wire schemas

**Files:**
- Modify: `gateway/app/modules/task/router.py`
- Modify: `gateway/app/modules/task/schema.py`
- Modify: `gateway/app/modules/task/api.py`
- Modify: `gateway/app/modules/task/service.py`
- Modify: `gateway/app/modules/task/legacy/api.py`
- Modify: `gateway/app/modules/task/legacy/adapter.py`
- Test: `gateway/tests/test_task_workspace_schema.py`
- Test: `gateway/tests/test_task_workspace_api.py`
- Test: `gateway/tests/test_routing.py`

**Interfaces:**
- Produces: `normalize_resource_url(url: str) -> str`
- Produces: `WorkspaceDescriptor`, `ActionId`, `HistoryMessage`, `DocumentDraft`, `WorkspaceRequest`, `WorkspaceResponse`
- Produces: `TaskService.workspace(request: WorkspaceRequest, *, user_id: str | None) -> WorkspaceResponse`

- [ ] **Step 1: Write failing router and schema tests**

```python
def test_linkedin_search_and_view_urls_share_resource() -> None:
    assert normalize_resource_url("https://www.linkedin.com/jobs/search/?currentJobId=4442412976") == (
        "https://www.linkedin.com/jobs/view/4442412976"
    )
    assert normalize_resource_url("https://www.linkedin.com/jobs/view/4442412976?trackingId=x") == (
        "https://www.linkedin.com/jobs/view/4442412976"
    )

def test_indeed_vjk_and_jk_share_resource() -> None:
    assert normalize_resource_url("https://ae.indeed.com/?vjk=a5f6724841c417a3") == (
        "https://ae.indeed.com/viewjob?jk=a5f6724841c417a3"
    )

def test_workspace_rejects_eleventh_input_message() -> None:
    with pytest.raises(ValidationError):
        WorkspaceRequest(url="https://example.com", resourceUrl="https://example.com/", actionId="ask_more",
                         histories=[{"role": "user", "content": str(i)} for i in range(10)], message="next")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd gateway && uv run pytest tests/test_task_workspace_schema.py tests/test_routing.py -q`

Expected: FAIL because Workspace schemas and `normalize_resource_url` do not exist.

- [ ] **Step 3: Implement schemas, normalization, service method, and `/tasks/workspace`**

```python
class ActionId(StrEnum):
    ANALYZE = "analyze"
    TAILOR_RESUME = "tailor_resume"
    WRITE_COVER_LETTER = "write_cover_letter"
    ASK_MORE = "ask_more"

class WorkspaceRequest(PageContext):
    resource_url: str = Field(alias="resourceUrl")
    action_id: ActionId = Field(alias="actionId")
    histories: list[HistoryMessage] = Field(default_factory=list, max_length=10)
    current_document: DocumentDraft | None = Field(default=None, alias="currentDocument")
    message: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def validate_message_limit(self) -> "WorkspaceRequest":
        if len(self.histories) + 1 > 10:
            raise ValueError("histories plus current message must not exceed 10")
        return self
```

The API calls `TaskService.workspace`; the service recomputes `resource_url`, rejects mismatches, appends the validated user and assistant messages, and returns all histories. Keep `/tasks/current-task` and `/tasks` unchanged for installed-extension compatibility.

- [ ] **Step 4: Run focused gateway tests**

Run: `cd gateway && uv run pytest tests/test_task_workspace_schema.py tests/test_task_workspace_api.py tests/test_routing.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the gateway contract**

```bash
git add gateway/app/modules/task gateway/tests/test_task_workspace_schema.py gateway/tests/test_task_workspace_api.py gateway/tests/test_routing.py
git commit -m "feat: add stateless workspace task contract"
```

### Task 2: Backend-declared Actions and Workspace execution

**Files:**
- Modify: `gateway/app/agents/base.py`
- Modify: `gateway/app/agents/job_match.py`
- Modify: `gateway/app/agents/summary_page.py`
- Modify: `gateway/app/modules/task/service.py`
- Test: `gateway/tests/test_job_match.py`
- Test: `gateway/tests/test_summary_page.py`
- Test: `gateway/tests/test_task_v2_service.py`

**Interfaces:**
- Produces: `TaskAgent.actions(ctx: AgentContext) -> list[Action]`
- Consumes: `WorkspaceRequest.action_id`, `.histories`, `.current_document`, and `.message`

- [ ] **Step 1: Write failing action and shared-history tests**

```python
def test_job_match_declares_workspace_actions(agent, quick_context) -> None:
    assert [a.id for a in agent.actions(quick_context)] == [
        ActionId.ANALYZE, ActionId.TAILOR_RESUME,
        ActionId.WRITE_COVER_LETTER, ActionId.ASK_MORE,
    ]

def test_workspace_prompt_contains_shared_history(agent, workspace_request) -> None:
    prompt = agent.build_prompt(workspace_request, cv_text="CV")
    assert "核心是 Agent 和 MCP" in prompt
    assert "突出我的 Go 项目" in prompt
```

- [ ] **Step 2: Verify the new tests fail**

Run: `cd gateway && uv run pytest tests/test_job_match.py tests/test_summary_page.py tests/test_task_v2_service.py -q`

Expected: FAIL because Agents do not declare the new Actions or consume histories.

- [ ] **Step 3: Implement Agent action strategies**

Add a documented `actions()` interface to `TaskAgent`. `JobMatchAgent` maps each `ActionId` to one prompt strategy; `SummaryPageAgent` accepts only `ASK_MORE`. Format histories as untrusted conversation context, include the current document text only for document-editing Actions, and keep all Agent instances stateless.

```python
def actions(self, ctx: AgentContext) -> list[Action]:
    """Return the task modes available for this routed page context."""

ACTION_TITLES = {
    ActionId.ANALYZE: "Analyze",
    ActionId.TAILOR_RESUME: "Tailor Resume",
    ActionId.WRITE_COVER_LETTER: "Generate Cover Letter",
    ActionId.ASK_MORE: "Ask More",
}
```

- [ ] **Step 4: Run Agent and service tests**

Run: `cd gateway && uv run pytest tests/test_job_match.py tests/test_summary_page.py tests/test_task_v2_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Agent execution**

```bash
git add gateway/app/agents gateway/app/modules/task/service.py gateway/tests
git commit -m "feat: route workspace actions through task agents"
```

### Task 3: Stable extension owner and local Workspace reducer

**Files:**
- Modify: `gateway/app/modules/auth/schema.py`
- Modify: `gateway/app/modules/auth/token_service.py`
- Modify: `frontend/src/extensionConnect.js`
- Modify: `extension/auth.js`
- Modify: `extension/auth.test.js`
- Create: `extension/workspace.js`
- Create: `extension/workspace.test.js`
- Test: `gateway/tests/test_extension_token_api.py`
- Test: `frontend/src/extensionConnect.test.js`

**Interfaces:**
- Produces: `WORKSPACE_OWNER_KEY`
- Produces: `workspaceStorageKey(ownerId, resourceUrl) -> string`
- Produces: `createWorkspace(seed)`, `applyWorkspaceResponse(state, response)`, `canSend(state)`

- [ ] **Step 1: Write failing identity and reducer tests**

```javascript
test("workspace key isolates owner and resource", () => {
  assert.notEqual(workspaceStorageKey("u1", "https://x/a"), workspaceStorageKey("u2", "https://x/a"));
});

test("response replaces histories instead of appending", () => {
  const next = applyWorkspaceResponse({ histories: [{ role: "user", content: "old" }] }, {
    histories: [{ role: "assistant", content: "canonical" }], document: null
  });
  assert.deepEqual(next.histories, [{ role: "assistant", content: "canonical" }]);
});
```

- [ ] **Step 2: Verify identity/reducer tests fail**

Run: `cd extension && node --test auth.test.js workspace.test.js`

Expected: FAIL because owner storage and Workspace reducer do not exist.

- [ ] **Step 3: Implement stable owner propagation and pure Workspace state helpers**

`ExtensionTokenIssued` returns `user_id`; `AUTH_TOKEN` stores it. `workspace.js` owns the storage-key format, default Action selection, the ten-input-message guard, and whole-state replacement.

- [ ] **Step 4: Run gateway, frontend, and extension focused tests**

Run: `cd gateway && uv run pytest tests/test_extension_token_api.py -q`

Run: `cd frontend && npm test -- --run src/extensionConnect.test.js`

Run: `cd extension && node --test auth.test.js workspace.test.js`

Expected: PASS for all commands.

- [ ] **Step 5: Commit identity and state helpers**

```bash
git add gateway/app/modules/auth frontend/src extension/auth.js extension/auth.test.js extension/workspace.js extension/workspace.test.js gateway/tests/test_extension_token_api.py
git commit -m "feat: persist owner-scoped browser workspaces"
```

### Task 4: Side Panel Workspace interaction

**Files:**
- Modify: `extension/manifest.json`
- Modify: `extension/background.js`
- Modify: `extension/content.js`
- Modify: `extension/quick-insight.test.js`
- Create: `extension/sidepanel.html`
- Create: `extension/sidepanel.css`
- Create: `extension/sidepanel.js`
- Create: `extension/sidepanel.test.js`
- Modify: `extension/package.sh`

**Interfaces:**
- Consumes: `workspaceStorageKey`, `createWorkspace`, `applyWorkspaceResponse`, `canSend`
- Produces runtime messages: `AGENT_BRIDGE_OPEN_WORKSPACE`, `AGENT_BRIDGE_WORKSPACE_GET`, `AGENT_BRIDGE_WORKSPACE_SEND`

- [ ] **Step 1: Write failing manifest, message-flow, and view-model tests**

```javascript
test("manifest declares Side Panel", async () => {
  const manifest = JSON.parse(await readFile(new URL("./manifest.json", import.meta.url)));
  assert.ok(manifest.permissions.includes("sidePanel"));
  assert.equal(manifest.side_panel.default_path, "sidepanel.html");
});

test("job actions stay flat and selected action survives history", () => {
  const view = workspaceView(state);
  assert.deepEqual(view.actions.map((a) => a.id), ["analyze", "tailor_resume", "write_cover_letter", "ask_more"]);
  assert.equal(view.selectedActionId, "tailor_resume");
});
```

- [ ] **Step 2: Verify Side Panel tests fail**

Run: `cd extension && node --test quick-insight.test.js sidepanel.test.js`

Expected: FAIL because the Side Panel files and message flow do not exist.

- [ ] **Step 3: Implement the Side Panel and background orchestration**

Quick Insight Action clicks send `AGENT_BRIDGE_OPEN_WORKSPACE`; background seeds/loads the owner-scoped Workspace and calls `chrome.sidePanel.open({tabId})`. The Side Panel renders one scrolling shared history, a latest-document card, flat Action chips immediately above a fixed composer, and replaces its state with each `/tasks/workspace` response.

Before every send, background asks `content.js` for fresh Page Context. It does not persist `pageText` or `selectedText` in Workspace storage.

- [ ] **Step 4: Run all extension tests and packaging check**

Run: `cd extension && npm test`

Run: `cd extension && npm run test:package`

Expected: all Node tests pass and the package contains `sidepanel.html`, `sidepanel.css`, `sidepanel.js`, and `workspace.js`.

- [ ] **Step 5: Commit the Side Panel**

```bash
git add extension
git commit -m "feat: add shared workspace side panel"
```

### Task 5: Documentation and full verification

**Files:**
- Modify: `gateway/app/modules/task/README.md`
- Modify: `extension/README.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/superpowers/specs/2026-07-18-shared-workspace-design.md`

**Interfaces:**
- Documents: `/tasks/quick-insight`, `/tasks/workspace`, local persistence, Action semantics, and the ten-message limit.

- [ ] **Step 1: Update user and module documentation**

Document that Context Routing and resource normalization live in the gateway, Workspace history remains local to one Chrome profile, Actions share one history, and `/tasks/current-task` is deprecated compatibility behavior.

- [ ] **Step 2: Run plan/spec consistency scans**

Run: `rg -n "agent.*browser_agent|Current Task|priorResult" docs/superpowers/specs/2026-07-18-shared-workspace-design.md gateway/app/modules/task/README.md extension/README.md`

Expected: matches appear only in explicit legacy/deprecation explanations.

- [ ] **Step 3: Run full verification**

Run: `cd gateway && uv run pytest`

Run: `cd gateway && uv run python -c "import app.main; print('main import ok')"`

Run: `cd frontend && npm test -- --run`

Run: `cd frontend && npm run build`

Run: `cd extension && npm test`

Run: `cd extension && npm run test:package`

Expected: every command exits 0; import prints `main import ok`.

- [ ] **Step 4: Commit documentation and final integration**

```bash
git add README.md README.zh-CN.md extension/README.md gateway/app/modules/task/README.md docs/superpowers/specs/2026-07-18-shared-workspace-design.md
git commit -m "docs: describe shared browser workspace"
```
