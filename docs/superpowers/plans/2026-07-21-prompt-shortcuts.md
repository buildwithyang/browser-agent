# Prompt Shortcuts Protocol v4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Workspace Action routing with localized, editable Prompt Shortcuts and enforce a true ten-user-turn limit across Gateway and Extension.

**Architecture:** Protocol v4 makes Quick Insight the server-owned capability catalogue and keeps Workspace as one message-only streaming endpoint. Gateway Agents expose localized Shortcut metadata, while `JobMatchAgent` plans every submitted message from message, artifacts, and shared history. The Extension stores Shortcut drafts but sends only the edited message, uses one-shot session prefill when entering from Quick Insight, and counts canonical user messages rather than total history records.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, `StrEnum`, AsyncOpenAI Chat Completions, NDJSON, Chrome Manifest V3 service worker and Side Panel APIs, JavaScript ES modules, Marked, DOMPurify, pytest, Node test runner.

## Global Constraints

- Implement the confirmed design in `docs/superpowers/specs/2026-07-21-prompt-shortcuts-design.md`; do not redesign the interaction during implementation.
- Make a clean protocol-v4 cut. Do not accept v3 Workspace payloads or ship v3/v4 dual parsing.
- Prompt Shortcuts only replace and focus the composer. They never call `/tasks/workspace`, append history, create an Artifact, or auto-send.
- `POST /tasks/workspace` accepts one non-empty user `message`; it never receives `trigger`, `actionId`, or any Shortcut identifier.
- Keep Workspace streaming on Chat Completions and NDJSON. Do not introduce SSE, WebSocket, polling, or the Responses API.
- Preserve atomic terminal commits: pending text and deltas never enter canonical histories or consume a turn after failure/cancellation.
- Count a turn from canonical `role=user` messages only. The tenth user send is legal; an eleventh is rejected by both Extension and Gateway.
- Analyze output uses a Markdown table with exactly the two requested columns: `JD 要求 | 匹配情况` in Chinese and `JD Requirement | Match` in English.
- Tailor Resume's initial Shortcut asks for a modification plan and does not directly create a CV. A later explicit confirmation may create or update the CV Artifact.
- Cover Letter remains a plain-text, copyable Attachment even though the Assistant note supports Markdown rendering.
- Keep Agents stateless and preserve API -> Service -> Repository -> DB boundaries. This feature changes no DB schema.
- Add concise docstrings/JSDoc to every new or changed Interface, abstract method, and function; comment the main phases of complex reducers and event flows.
- Use `apply_patch` for source edits. Preserve unrelated user changes in the existing `main` worktree.
- Run each task's focused tests before committing. Do not move to the next task while the focused suite is red.

---

## File map

### Gateway

- Modify `gateway/app/modules/task/schema.py`: Prompt Shortcut contract, message-only Workspace request, Action-free history/response, and ten-turn validation.
- Modify `gateway/app/modules/task/protocol.py`: protocol version `4`.
- Modify `gateway/app/agents/base.py`: replace `available_actions()` with `available_shortcuts()` and remove Action context from model formatting.
- Modify `gateway/app/agents/job_match/quick_insight.py`: localized Job Match Shortcut catalogue.
- Modify `gateway/app/agents/job_match/context.py`: Action-free required current message.
- Modify `gateway/app/agents/job_match/agent.py`: remove deterministic Quick Action plans and plan every Workspace message.
- Modify `gateway/app/agents/job_match/planner.py`: plan from message, artifacts, then history.
- Modify `gateway/app/agents/job_match/specialists/base.py`: remove trigger/Action prompt fields.
- Modify `gateway/app/agents/job_match/specialists/analysis.py`: exact two-column JD comparison output.
- Modify `gateway/app/agents/summary_page.py`: localized empty Ask More Shortcut and message-only chat.
- Modify `gateway/app/modules/task/service.py`: return Shortcuts and reduce every successful request as a user/Assistant pair.
- Modify Gateway protocol, schema, Agent, service, API, streaming, routing, and language tests named below.

### Extension

- Modify `extension/config.js`: wire protocol version `4`.
- Modify `extension/workspace.js`: local schema v3, Shortcut validation, Action-free state, and user-turn counting.
- Modify `extension/workspace-controller.js`: v2 -> v3 migration and one-shot session prefill storage.
- Modify `extension/auth.js`: message-only Workspace body.
- Modify `extension/workspace-operation.js`: remove Quick Action operations and Action metadata.
- Modify `extension/quick-insight.js`: turn Quick Insight clicks into open-and-prefill commands.
- Modify `extension/background.js`: seed Shortcuts, consume prefill once, and submit only final composer text.
- Modify `extension/sidepanel.js`: Shortcut composer behavior, ten-turn meter, and disabled-limit state.
- Modify `extension/sidepanel.html` and `extension/sidepanel.css`: Shortcut semantics and limit presentation where required.
- Modify all corresponding Extension tests and production package assertions.

### Release and documentation

- Modify `extension/manifest.json`: release version `0.3.0`.
- Modify `extension/package.json` and `extension/package-lock.json`: keep package metadata at `0.3.0`.
- Modify `extension/distribution.test.js` and `extension/scripts/verify-package.mjs`: verify source and packaged release metadata.
- Modify `README.md`, `README.zh-CN.md`, and `extension/README.md`: user-facing Prompt Shortcut and ten-turn behavior.
- Modify `gateway/app/modules/task/README.md` and `gateway/app/agents/job_match/README.md`: protocol-v4 contracts and orchestration.
- Modify `docs/superpowers/specs/2026-07-18-shared-workspace-design.md` and `docs/superpowers/specs/2026-07-20-workspace-streaming-design.md`: remove superseded Action and ten-message statements.

---

### Task 1: Migrate the complete Gateway to the protocol-v4 Prompt Shortcut contract

**Files:**
- Modify: `gateway/app/modules/task/schema.py`
- Modify: `gateway/app/modules/task/protocol.py`
- Modify: `gateway/tests/test_task_protocol.py`
- Modify: `gateway/tests/test_task_schema.py`
- Modify: `gateway/tests/test_task_workspace_schema.py`
- Modify: `gateway/tests/test_task_workspace_stream_schema.py`

**Interfaces:**
- Produces: `PromptShortcutId`, `PromptShortcut`, `WorkspaceRequest`, `count_user_turns(histories) -> int`.
- Changes: `QuickInsightResponse.actions` -> `QuickInsightResponse.shortcuts`.
- Changes: `WorkspaceDescriptor` to only `resource_url`.
- Removes: `Action`, `ActionId`, `WorkspaceTrigger`, `UserMessageWorkspaceRequest`, `QuickInsightActionWorkspaceRequest`, history `action_id`, and response `selected_action_id`.
- Preserves: `operationId`, `WorkspaceResultType`, Artifact schemas, strict extra-field rejection, and NDJSON terminal event envelope.

- [ ] **Step 1: Write failing protocol and schema tests**

Replace v3 expectations with v4 and add strict contract tests:

```python
def test_workspace_request_accepts_only_one_user_message_shape() -> None:
    request = WorkspaceRequest.model_validate(
        {
            "operationId": str(uuid4()),
            "url": "https://example.com/role",
            "resourceUrl": "https://example.com/role",
            "histories": [],
            "artifacts": {"cv": None, "cover_letter": None},
            "message": "Analyze this role.",
        }
    )
    assert request.message == "Analyze this role."


@pytest.mark.parametrize(
    ("field", "value"),
    [("trigger", "user_message"), ("actionId", "analyze")],
)
def test_workspace_request_rejects_removed_action_fields(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError, match=field):
        WorkspaceRequest.model_validate({**workspace_payload(), field: value})


def test_history_and_response_reject_removed_action_fields() -> None:
    with pytest.raises(ValidationError, match="action_id"):
        HistoryMessage.model_validate(
            {"role": "user", "content": "Hello", "action_id": "ask_more"}
        )
    with pytest.raises(ValidationError, match="selected_action_id"):
        WorkspaceResponse.model_validate(
            {**workspace_response_payload(), "selected_action_id": "analyze"}
        )
```

Add Prompt Shortcut validation tests for strict keys, stable enum IDs, localized titles, non-empty
job prompts, and the intentionally empty Ask More prompt:

```python
def test_prompt_shortcut_allows_empty_ask_more_prompt() -> None:
    shortcut = PromptShortcut(
        id=PromptShortcutId.ASK_MORE,
        title="继续提问",
        prompt="",
    )
    assert shortcut.prompt == ""


def test_workspace_allows_tenth_user_turn_but_rejects_eleventh() -> None:
    nine_turns = paired_histories(turns=9)
    assert count_user_turns(nine_turns) == 9
    assert WorkspaceRequest.model_validate(
        {**workspace_payload(), "histories": dump_histories(nine_turns)}
    )

    with pytest.raises(ValidationError, match="10 user turns"):
        WorkspaceRequest.model_validate(
            {**workspace_payload(), "histories": dump_histories(paired_histories(turns=10))}
        )
```

Update stream schema tests so a `completed` event accepts the Action-free v4 `WorkspaceResponse`
and rejects the removed field.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd gateway
uv run pytest tests/test_task_protocol.py tests/test_task_schema.py tests/test_task_workspace_schema.py tests/test_task_workspace_stream_schema.py -q
```

Expected: failures because protocol is still `3`, `PromptShortcut` does not exist, and the old
discriminated Action request still requires `trigger` and `actionId`.

- [ ] **Step 3: Implement the strict v4 schemas**

Use one stable enum for Shortcut display identity only:

```python
class PromptShortcutId(StrEnum):
    """Stable Prompt Shortcut identities returned by Quick Insight."""

    ANALYZE = "analyze"
    TAILOR_RESUME = "tailor_resume"
    WRITE_COVER_LETTER = "write_cover_letter"
    ASK_MORE = "ask_more"


class PromptShortcut(BaseModel):
    """Localized editable composer draft declared by a routed Agent."""

    model_config = ConfigDict(extra="forbid")

    id: PromptShortcutId
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    prompt: str = Field(max_length=USER_MESSAGE_MAX_CHARS)
```

Replace the request union with one strict model and centralize user-turn counting:

```python
MAX_WORKSPACE_TURNS = 10
MAX_WORKSPACE_HISTORIES = MAX_WORKSPACE_TURNS * 2


def count_user_turns(histories: list[HistoryMessage]) -> int:
    """Count completed canonical user sends in shared Workspace history."""

    return sum(message.role == "user" for message in histories)


class WorkspaceRequest(PageContext):
    """One message-only protocol-v4 Workspace transition request."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_url: str = Field(alias="resourceUrl")
    operation_id: UUID = Field(alias="operationId")
    histories: list[HistoryMessage] = Field(default_factory=list, max_length=MAX_WORKSPACE_HISTORIES)
    artifacts: Artifacts
    message: str = Field(min_length=1, max_length=USER_MESSAGE_MAX_CHARS)

    @model_validator(mode="after")
    def validate_workspace_request(self) -> "WorkspaceRequest":
        """Validate canonical state and reserve the next user turn."""

        validate_workspace_state(self.histories, self.artifacts)
        if count_user_turns(self.histories) >= MAX_WORKSPACE_TURNS:
            raise ValueError("Workspace already contains 10 user turns")
        return self
```

Set `CURRENT_EXTENSION_PROTOCOL_VERSION = 4`, make `WorkspaceResponse.histories` use
`MAX_WORKSPACE_HISTORIES`, remove `selected_action_id`, and preserve `extra="forbid"` on all
affected boundary models. Remove stale Action-specific exports and imports from these files only;
downstream compile failures are intentionally resolved in Task 2.

- [ ] **Step 4: Run the schema tests as an implementation checkpoint**

Run the Step 2 command.

Expected: pure schema assertions pass with v4 bodies and strict removed-field rejection. Tests that
import `app.main` may still fail at old Agent/service consumers; record those failures and continue
within this same task. Do not commit or hand off this schema-only state.

#### Agent and service integration

**Files:**
- Modify: `gateway/app/agents/base.py`
- Modify: `gateway/app/agents/job_match/quick_insight.py`
- Modify: `gateway/app/agents/job_match/context.py`
- Modify: `gateway/app/agents/job_match/agent.py`
- Modify: `gateway/app/agents/job_match/planner.py`
- Modify: `gateway/app/agents/job_match/specialists/base.py`
- Modify: `gateway/app/agents/job_match/specialists/analysis.py`
- Modify: `gateway/app/agents/summary_page.py`
- Modify: `gateway/app/modules/task/service.py`
- Modify: `gateway/tests/test_job_match.py`
- Modify: `gateway/tests/test_job_match_orchestrator.py`
- Modify: `gateway/tests/test_job_match_planner.py`
- Modify: `gateway/tests/test_job_match_specialists.py`
- Modify: `gateway/tests/test_language.py`
- Modify: `gateway/tests/test_summary_page.py`
- Modify: `gateway/tests/test_task_workspace_service.py`
- Modify: `gateway/tests/test_task_workspace_api.py`
- Modify: `gateway/tests/test_task_rate_limit.py`
- Modify: `gateway/tests/test_routing.py`

**Interfaces:**
- Changes: `QuickInsightAgent.available_actions(context)` -> `available_shortcuts(context)`.
- Changes: `JobChatContext.current_message` to required `str`; removes `trigger` and `selected_action`.
- Consumes: `PromptShortcut`, `PromptShortcutId`, message-only `WorkspaceRequest`.
- Produces: Action-free `QuickInsightResponse` and `WorkspaceResponse` in both synchronous and streamed paths.

- [ ] **Step 5: Write failing Agent and service tests**

Add exact Shortcut catalogue tests for both languages:

```python
def test_job_match_returns_localized_zh_prompt_shortcuts() -> None:
    response = service.quick_insight(quick_request(lang="zh"), user_id="user-1")

    assert [shortcut.id for shortcut in response.shortcuts] == [
        PromptShortcutId.ANALYZE,
        PromptShortcutId.TAILOR_RESUME,
        PromptShortcutId.WRITE_COVER_LETTER,
        PromptShortcutId.ASK_MORE,
    ]
    assert response.shortcuts[0].prompt == (
        "请分析这个岗位真正看重的能力，并以 Markdown 表格逐项对比“JD 要求”和“匹配情况”。"
        "表格后总结我的匹配优势、核心差距，以及是否值得申请，并给出明确结论和理由。"
    )
    assert response.shortcuts[-1].prompt == ""
    assert response.workspace.model_dump() == {"resource_url": NORMALIZED_URL}
```

Assert the English Analyze prompt contains the exact column contract from the spec, Tailor Resume
says to wait for confirmation, Cover Letter asks for a concise complete draft, and Summary Page
returns only an empty Ask More Shortcut.

Replace Action-planner tests with message-first planning tests:

```python
async def test_every_workspace_message_uses_chat_planner() -> None:
    planner = StubPlanner(
        ChatPlan(specialist=SpecialistId.JOB_ANALYSIS, output_mode=OutputMode.REPLY)
    )
    agent = build_agent(planner=planner)

    await collect(agent.stream_chat(workspace_context(message="Analyze this role.")))

    assert planner.contexts[0].current_message == "Analyze this role."


def test_workspace_reducer_appends_action_free_user_and_assistant_messages() -> None:
    response = service.workspace(workspace_request(message="What matters?"), user_id="user-1")
    assert [message.role for message in response.histories[-2:]] == ["user", "assistant"]
    assert all("action_id" not in message.model_dump() for message in response.histories)
    assert "selected_action_id" not in response.model_dump()
```

Add planner prompt assertions for the priority order `current message > current artifacts >
histories`, and analysis specialist assertions requiring a two-column Markdown table:

```text
| JD 要求 | 匹配情况 |
| --- | --- |
```

The specialist instruction must forbid extra comparison columns; narrative conclusions follow the
table. Cover the corresponding English header in language tests.

- [ ] **Step 6: Run the focused tests and verify RED**

Run:

```bash
cd gateway
uv run pytest tests/test_job_match.py tests/test_job_match_orchestrator.py tests/test_job_match_planner.py tests/test_job_match_specialists.py tests/test_language.py tests/test_summary_page.py tests/test_task_workspace_service.py tests/test_task_workspace_api.py tests/test_task_rate_limit.py tests/test_routing.py -q
```

Expected: import and assertion failures from removed Action types, `available_actions`, deterministic
Quick Action plans, and Action fields in service responses.

- [ ] **Step 7: Implement localized Prompt Shortcut catalogues**

Change the Quick Insight Protocol method:

```python
@runtime_checkable
class QuickInsightAgent(Protocol):
    """Explicit interface for the read-only Quick Insight operation."""

    name: AgentName
    requires_resume: bool

    def quick_insight(self, context: AgentContext) -> AgentExecution[Insight]:
        """Generate the typed decision-first insight for the current page."""

        raise NotImplementedError

    def available_shortcuts(self, context: AgentContext) -> list[PromptShortcut]:
        """Return localized editable Prompt Shortcuts for the routed page."""

        raise NotImplementedError
```

In `job_match/quick_insight.py`, define immutable zh/en title and prompt catalogues with the exact
strings from the approved spec. In `JobMatchAgent.available_shortcuts()`, return the four ordered
items. In `SummaryPageAgent.available_shortcuts()`, return only localized Ask More with `prompt=""`.
Use `zh` only when `context.request.lang == "zh"`; otherwise use English, matching the existing
resolved-output-language behavior.

Update `TaskService.quick_insight()` to call `available_shortcuts(ctx)` and construct only:

```python
return QuickInsightResponse(
    request=request,
    insight=execution.content,
    shortcuts=agent.available_shortcuts(ctx),
    workspace=WorkspaceDescriptor(resource_url=resource_url),
    meta=meta,
)
```

- [ ] **Step 8: Remove Action routing from chat orchestration**

Delete `JOB_WORKSPACE_ACTION_IDS`, `QUICK_PLAN_BY_ACTION`, and all Quick Insight Action execution
branches. Make the domain context explicit:

```python
@dataclass(frozen=True)
class JobChatContext:
    """Complete request-scoped state used by the Job Match orchestrator."""

    request: WorkspaceRequest
    resume_text: str
    histories: tuple[HistoryMessage, ...]
    artifacts: Artifacts
    current_message: str
```

`JobMatchAgent._select_plan()` must always await `ChatPlanner.plan(context)`. Update planner and
specialist context formatting to include, in order:

```text
# Current user message
{current_message}
# Current artifacts
{formatted_artifacts}
# Shared conversation history
{formatted_histories}
```

Do not infer intent from a Shortcut ID because none reaches the Agent. Preserve the planner's strict
`reply | create_artifact | update_artifact` result semantics and existing Artifact preconditions.
The Tailor Resume Shortcut text naturally plans a Resume specialist reply first; a later explicit
confirmation can plan a create/update Artifact using history and current Artifact state.

Make `JobAnalysisAgent` instruct the model to emit the exact localized two-column comparison table
before strengths, gaps, and apply recommendation. Do not alter the generic Markdown renderer.

- [ ] **Step 9: Make both Workspace reducers message-only**

Remove conditional user-message insertion from `_reduce_workspace_state()`: every request appends
one user message followed by one Assistant message at the same Action-free shape. Remove
`selected_action_id` from both `TaskService.workspace()` and `TaskService.stream_workspace()`
terminal responses. Update validation helpers, input-char accounting, and log context to use
`request.message` directly rather than `getattr()` or trigger checks.

Keep failures atomic: neither synchronous nor streaming failure may return/persist either new
history record.

- [ ] **Step 10: Run the focused tests and verify GREEN**

Run the Step 6 command.

Expected: all selected Agent, service, routing, language, API, and streaming tests pass under the
message-only v4 contract.

- [ ] **Step 11: Run the complete Gateway suite and commit Task 1**

Run before committing:

```bash
cd gateway
uv run pytest
uv run python -c "import app.main; print('main import ok')"
```

Expected: all Gateway tests pass with zero failures and import prints `main import ok`.

```bash
git add gateway/app/modules/task/schema.py gateway/app/modules/task/protocol.py gateway/app/modules/task/service.py gateway/app/agents/base.py gateway/app/agents/job_match/quick_insight.py gateway/app/agents/job_match/context.py gateway/app/agents/job_match/agent.py gateway/app/agents/job_match/planner.py gateway/app/agents/job_match/specialists/base.py gateway/app/agents/job_match/specialists/analysis.py gateway/app/agents/summary_page.py gateway/tests
git commit -m "feat: migrate gateway to prompt shortcut protocol v4"
```

---

### Task 2: Migrate Extension storage, transport, and both Shortcut interfaces to protocol v4

**Files:**
- Modify: `extension/config.js`
- Modify: `extension/workspace.js`
- Modify: `extension/workspace-controller.js`
- Modify: `extension/auth.js`
- Modify: `extension/workspace-operation.js`
- Modify: `extension/background.js`
- Modify: `extension/auth.test.js`
- Modify: `extension/workspace.test.js`
- Modify: `extension/workspace-controller.test.js`
- Modify: `extension/workspace-operation.test.js`
- Modify: `extension/background.test.js`
- Modify: `extension/workspace-stream.test.js`

**Interfaces:**
- Produces: local Workspace schema v3 with `shortcuts` and no selection state.
- Produces: `countUserTurns(histories) -> number` and `canSendUserMessage(state) -> boolean`.
- Produces: one-shot `storeWorkspacePrefill(tabId, shortcut)` and `consumeWorkspacePrefill(tabId)` session helpers.
- Changes: Workspace request builder to `{operationId, page context, resourceUrl, histories, artifacts, message}` only.
- Removes: Quick Action operation kinds, `trigger`, `actionId`, `actions`, `selectedActionId`, and v1 migration.

- [ ] **Step 1: Write failing local schema and transport tests**

Add strict Shortcut/state validation and v2 migration coverage:

```javascript
test("migrates v2 workspace to v3 without losing histories or artifacts", () => {
  const migrated = migrateWorkspaceV2({
    schemaVersion: 2,
    resourceUrl: "https://example.com/role",
    pageTitle: "Role",
    quickInsight: { title: "Job Match", cards: [] },
    actions: [{ id: "analyze", title: "Analyze" }],
    selectedActionId: "analyze",
    histories: [history({ role: "user", content: "Hello", action_id: "analyze" })],
    artifacts: emptyArtifacts(),
    updatedAt: "2026-07-21T10:00:00.000Z",
  });

  assert.equal(migrated.schemaVersion, 3);
  assert.deepEqual(migrated.shortcuts, []);
  assert.equal(migrated.histories[0].content, "Hello");
  assert.equal("action_id" in migrated.histories[0], false);
  assert.deepEqual(migrated.artifacts, emptyArtifacts());
  assert.equal("actions" in migrated, false);
  assert.equal("selectedActionId" in migrated, false);
});
```

Delete v1 migration assertions and test that unsupported v1 state is discarded. Add true turn tests:

```javascript
test("allows ten user sends regardless of assistant message count", () => {
  const nineTurns = pairedHistories(9);
  assert.equal(countUserTurns(nineTurns), 9);
  assert.equal(canSendUserMessage({ histories: nineTurns }), true);

  const tenTurns = pairedHistories(10);
  assert.equal(countUserTurns(tenTurns), 10);
  assert.equal(canSendUserMessage({ histories: tenTurns }), false);
});
```

Update auth/operation tests to expect this exact body omission:

```javascript
assert.deepEqual(workspaceBody, {
  operationId,
  url,
  title,
  selectedText,
  pageText,
  imageText,
  intent,
  lang,
  resourceUrl,
  histories,
  artifacts,
  message: "Edited final prompt",
});
assert.equal("trigger" in workspaceBody, false);
assert.equal("actionId" in workspaceBody, false);
```

Add session-prefill tests proving it is isolated per tab, returned once, deleted after consumption,
and removed by tab reset. Use a Shortcut object rather than a plain string so empty Ask More remains
distinguishable from no pending prefill.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd extension
node --test auth.test.js workspace.test.js workspace-controller.test.js workspace-operation.test.js background.test.js workspace-stream.test.js
```

Expected: failures because storage is schema v2, transport still requires Action fields, and no
one-shot prefill API exists.

- [ ] **Step 3: Implement local Workspace schema v3**

Set constants and state helpers:

```javascript
export const WORKSPACE_SCHEMA_VERSION = 3;
export const MAX_WORKSPACE_TURNS = 10;
export const MAX_WORKSPACE_HISTORIES = 20;

export function countUserTurns(histories = []) {
  return histories.reduce(
    (count, message) => count + (message?.role === "user" ? 1 : 0),
    0
  );
}

export function canSendUserMessage(state) {
  return countUserTurns(state?.histories) < MAX_WORKSPACE_TURNS;
}
```

Validate each Shortcut as exactly `id`, `title`, and `prompt`; permit `prompt === ""`. Persist only:

```text
schemaVersion/resourceUrl/pageTitle/quickInsight/shortcuts/histories/artifacts/updatedAt
```

Remove all Action selection helpers. Implement only v2 -> v3 migration, preserve message IDs,
roles, content, timestamps, attachments, Artifact snapshots, page metadata, and Quick Insight, and
strip `action_id` from each history record. Initialize `shortcuts: []`; the next successful Quick
Insight seed replaces them with the current server catalogue. Discard unsupported v1 and malformed
states rather than recursively migrating them.

- [ ] **Step 4: Implement one-shot prefill and message-only operations**

Use a tab-scoped `chrome.storage.session` key separate from durable Workspace content:

```javascript
export function workspacePrefillKey(tabId) {
  return `agent-bridge:workspace-prefill:${tabId}`;
}

export async function storeWorkspacePrefill(tabId, shortcut) {
  /** Persist one server-declared draft until the Side Panel consumes it. */
}

export async function consumeWorkspacePrefill(tabId) {
  /** Atomically read and delete one pending composer draft for a tab. */
}
```

Serialize `store`/`consume` with the existing per-tab seed queue so `WORKSPACE_GET` cannot race ahead
of a Quick Insight seed. `seedWorkspace()` stores the full `shortcuts` catalogue and, when the open
message includes one selected Shortcut, stores that Shortcut as the pending one-shot prefill.
`WORKSPACE_GET` waits for the seed queue, returns `{ state, prefill }`, then removes the prefill.
Workspace reset and tab removal delete both the active mapping and prefill key.

Replace operation creation with one user-message shape:

```javascript
export function createUserMessageOperation(message) {
  /** Create one message-only Workspace operation from edited composer text. */

  const normalized = String(message || "").trim();
  if (!normalized) throw new TypeError("Workspace message is required");
  return { kind: "user_message", message: normalized };
}
```

Remove Action translation maps and Quick Action request execution. `background.js` must submit only
the operation message plus the latest canonical Workspace state and fresh page context. Keep
operation UUIDs, abort ownership, NDJSON parsing, progressive snapshots, and terminal commit logic
unchanged. Set `EXTENSION_PROTOCOL_VERSION = 4`.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run the Step 2 command.

Expected: all selected storage, transport, operation, background, and streaming tests pass with
schema v3 and protocol v4.

- [ ] **Step 6: Continue directly to both UI entry points**

Do not commit or hand off the storage/transport-only state: Quick Insight and Side Panel still consume
the old Action view model. Continue within this same Extension task until all runtime imports and the
full Extension suite use the v4 state shape.

#### Quick Insight and Side Panel integration

**Files:**
- Modify: `extension/quick-insight.js`
- Modify: `extension/background.js`
- Modify: `extension/sidepanel.js`
- Modify: `extension/sidepanel.html`
- Modify: `extension/sidepanel.css`
- Modify: `extension/quick-insight.test.js`
- Modify: `extension/background.test.js`
- Modify: `extension/sidepanel.test.js`

**Interfaces:**
- Consumes: server `shortcuts` and one-shot `{id, title, prompt}` prefill.
- Produces: `OPEN_WORKSPACE` seed/open message containing the selected Shortcut but no execution command.
- Removes: selected-chip state, `aria-pressed`, default Action, and Action-dependent send guards.

- [ ] **Step 7: Write failing Quick Insight and Side Panel interaction tests**

Cover both entry points:

```javascript
test("Quick Insight shortcut opens and prefills without executing workspace", async () => {
  const analyze = shortcut({ id: "analyze", prompt: "Analyze the role." });
  await clickQuickInsightShortcut(analyze);

  assert.deepEqual(sentMessages, [
    {
      type: "OPEN_WORKSPACE",
      quickInsight,
      shortcuts,
      shortcut: analyze,
      workspace,
      pageTitle,
    },
  ]);
  assert.equal(fetchCalls.length, 0);
});


test("Side Panel shortcut replaces composer and Ask More clears it", async () => {
  messageInput.value = "Existing draft";
  clickShortcut("analyze");
  assert.equal(messageInput.value, "Analyze the role.");
  assert.equal(document.activeElement, messageInput);

  clickShortcut("ask_more");
  assert.equal(messageInput.value, "");
  assert.equal(document.activeElement, messageInput);
});
```

Add tests that a consumed Quick Insight prefill initializes the composer but does not auto-send,
and that it is ignored when ten user turns already exist.

Cover the meter and pending rollback:

```javascript
test("tenth pending send shows 10 / 10 and failure restores 9 / 10", async () => {
  renderState({ histories: pairedHistories(9) });
  submit("Final question");
  assert.equal(turnMeter.textContent, "10 / 10");

  emitFailedStream();
  assert.equal(turnMeter.textContent, "9 / 10");
  assert.equal(messageInput.disabled, false);
});
```

At ten completed user turns, assert all Shortcut buttons, textarea, and send button are disabled;
the keyboard hint is hidden; and placeholders are exactly:

```text
zh: 当前最多支持10轮聊天
en: This Workspace supports up to 10 turns.
```

Verify submit sends only the edited text even when it originated from a Shortcut.

- [ ] **Step 8: Run the focused tests and verify RED**

Run:

```bash
cd extension
node --test quick-insight.test.js background.test.js sidepanel.test.js
```

Expected: failures because Quick Insight still executes non-Ask-More Actions, Side Panel tracks a
selected Action, the meter counts all history records, and the old limit copy remains.

- [ ] **Step 9: Implement open-and-prefill Quick Insight behavior**

Render `payload.shortcuts` as wrapping chip-style buttons using the existing light Side Panel visual
language. On click, send only the Workspace seed and selected Shortcut to Background, then open the
Side Panel. Delete all branches that call Workspace for a Quick Insight Action. Ask More follows the
same route with an empty `prompt`, which intentionally clears the composer.

In Background, validate that the selected Shortcut exactly matches an item in the server-provided
catalogue by ID and prompt before writing the one-shot prefill. Seed/open still works when no
Shortcut is selected, but it does not change the composer.

- [ ] **Step 10: Implement stateless Side Panel Shortcut chips**

Replace Action selection with direct draft replacement:

```javascript
function applyPromptShortcut(shortcut) {
  /** Replace the editable draft with one server-declared Shortcut prompt. */

  if (!canSendCurrentTurn()) return;
  elements.messageInput.value = shortcut.prompt;
  elements.messageInput.focus();
  refreshComposerControls();
}
```

Do not style one Shortcut as selected and do not retain its ID. On initial `WORKSPACE_GET`, apply a
returned one-shot prefill once. Later Workspace updates refresh the catalogue without overwriting an
in-progress user draft. The send guard depends only on non-empty edited text, loading state, active
tab, and remaining user turns.

- [ ] **Step 11: Implement true ten-turn UI state**

Compute the meter as canonical user count plus one transient pending user message. A pending tenth
send disables the composer during generation and displays `10 / 10`; a failure/cancel restores the
canonical `9 / 10`. A terminal completed response already includes the new user and Assistant
messages, so clear pending state before recounting to avoid `11 / 10`.

When canonical user count reaches ten:

- disable every Shortcut button, textarea, and send button;
- set the exact localized limit placeholder;
- hide the `Enter` / `Shift + Enter` keyboard hint;
- ignore new prefill messages and keyboard submission;
- keep history and Artifact copy controls usable.

Do not count Assistant status text, streaming deltas, failed turns, Artifact Attachments, or Quick
Insight as turns.

- [ ] **Step 12: Run the focused tests and verify GREEN**

Run the Step 8 command.

Expected: all selected UI tests pass, both Shortcut entry points only prefill, and true ten-turn
pending/success/failure states are stable.

- [ ] **Step 13: Run the complete Extension suite and commit Task 2**

Run before committing:

```bash
cd extension
npm test
```

Expected: all Extension tests pass with zero failures.

```bash
git add extension/config.js extension/workspace.js extension/workspace-controller.js extension/auth.js extension/workspace-operation.js extension/quick-insight.js extension/background.js extension/sidepanel.js extension/sidepanel.html extension/sidepanel.css extension/auth.test.js extension/workspace.test.js extension/workspace-controller.test.js extension/workspace-operation.test.js extension/workspace-stream.test.js extension/quick-insight.test.js extension/background.test.js extension/sidepanel.test.js
git commit -m "feat: migrate extension to prompt shortcut protocol v4"
```

---

### Task 3: Release protocol v4, synchronize documentation, and verify the complete workflow

**Files:**
- Modify: `extension/manifest.json`
- Modify: `extension/package.json`
- Modify: `extension/package-lock.json`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `extension/README.md`
- Modify: `gateway/app/modules/task/README.md`
- Modify: `gateway/app/agents/job_match/README.md`
- Modify: `docs/superpowers/specs/2026-07-18-shared-workspace-design.md`
- Modify: `docs/superpowers/specs/2026-07-20-workspace-streaming-design.md`
- Modify: `extension/distribution.test.js`
- Modify: `extension/scripts/verify-package.mjs`
- Modify any remaining Gateway or Extension tests discovered by the full suites; do not weaken their assertions.

**Interfaces:**
- Publishes: Extension `0.3.0`, wire protocol `4`, local Workspace schema `3`.
- Documents: Quick Insight -> editable Prompt Shortcut -> shared-history Workspace -> message-driven Agent planning.
- Verifies: old extension protocol rejection, fresh install, v2 storage migration, production ZIP, and full automated suites.

- [ ] **Step 1: Write failing release/package assertions**

Update distribution and extracted-package tests to require:

```javascript
assert.equal(manifest.version, "0.3.0");
assert.equal(packageJson.version, manifest.version);
assert.equal(packagedConfig.EXTENSION_PROTOCOL_VERSION, 4);
assert.doesNotMatch(packagedBackground, /quick_insight_action|selectedActionId/);
```

Add one protocol middleware test proving header `3` receives `426 Upgrade Required` and header `4`
reaches normal body validation/handling. The invalid-protocol test must use an otherwise valid v4
body so the Header is the sole failure boundary.

- [ ] **Step 2: Run release-focused tests and verify RED**

Run:

```bash
cd gateway
uv run pytest tests/test_task_protocol.py -q
cd ../extension
node --test distribution.test.js
```

Expected: manifest/package assertions fail until version and production bundle inputs are updated.

- [ ] **Step 3: Update release metadata and user/engineering documentation**

Set `extension/manifest.json`, `extension/package.json`, and the root package entries in
`extension/package-lock.json` to `0.3.0`. Update user-facing READMEs in plain product language:

- LinkedIn/Indeed Quick Insight offers Analyze, Tailor Resume, Cover Letter, and Ask More as editable
  Prompt Shortcuts.
- Ordinary pages offer Ask More.
- Shortcut clicks prefill but never send automatically.
- Workspace shares history and permits ten user turns.
- At the limit, the user can still read history and copy generated content.

Update Task and Job Match module READMEs with exact v4 JSON examples. Remove `actions`,
`default_action_id`, `trigger`, `actionId`, history `action_id`, and `selected_action_id`; show
`shortcuts`, one message-only request, and an Action-free completed NDJSON response. Explain the
planner boundary and the exact Analyze table requirement.

Mark old shared-workspace and streaming design sections as superseded by protocol v4 where their
Action or total-message assumptions differ. Link to the approved Prompt Shortcut spec rather than
duplicating conflicting contracts.

- [ ] **Step 4: Run both complete automated suites**

Run:

```bash
cd gateway
uv run pytest
uv run python -c "import app.main; print('main import ok')"
cd ../extension
npm test
```

Expected: all Gateway and Extension tests pass with zero failures, and the Gateway import prints
`main import ok`.

- [ ] **Step 5: Build and inspect the production Extension package**

Run the repository's documented production package command from `extension/`, then inspect the ZIP
without installing it:

```bash
cd extension
npm run test:package
unzip -l dist/agent-bridge-extension.zip
unzip -p dist/agent-bridge-extension.zip manifest.json | rg '"version": "0.3.0"'
unzip -p dist/agent-bridge-extension.zip config.js | rg 'EXTENSION_PROTOCOL_VERSION = 4'
```

Expected: one production ZIP contains all Side Panel runtime modules, manifest `0.3.0`, and protocol
constant `4`; it contains no tests, source maps, credentials, or local development URL override.

- [ ] **Step 6: Perform one manual coordinated-upgrade smoke test**

With local Gateway running and the unpacked Extension reloaded:

1. Send one valid request with protocol header `3`; confirm the Extension update UI appears after
   Gateway returns 426.
2. Reload Extension `0.3.0`, open a LinkedIn or Indeed job, and confirm four localized Shortcuts.
3. Click Analyze in Quick Insight; confirm the Side Panel opens with the localized prompt populated
   and zero new history messages.
4. Edit and send it; confirm streamed Markdown begins before completion and contains the exact
   two-column JD comparison table.
5. Click Tailor Resume; confirm it replaces the draft and first returns a change plan rather than a
   CV. Explicitly confirm generation and verify the CV Artifact path still works.
6. Click Cover Letter; confirm the generated Attachment is plain copyable text. Ask for a shorter
   version and confirm the existing Artifact is updated.
7. Reach ten user sends; confirm `10 / 10`, disabled Shortcuts/composer/send, exact localized limit
   placeholder, hidden keyboard hint, and still-working copy controls.
8. Repeat with a v2 local Workspace fixture and confirm history/Artifacts survive migration while
   Action fields disappear.

- [ ] **Step 7: Review the final diff for contract leaks**

Run:

```bash
git diff --check
rg -n "quick_insight_action|selected_action_id|selectedActionId|default_action_id|defaultActionId|action_id|actionId|available_actions" gateway/app gateway/tests extension --glob '!dist/**'
git status --short
```

Expected: `git diff --check` is clean. Any remaining search hit is either a deliberate strict
rejection/migration test or a historical document explicitly marked superseded; no runtime path
uses an Action as input.

- [ ] **Step 8: Commit Task 3**

```bash
git add extension/manifest.json extension/package.json extension/package-lock.json extension/distribution.test.js extension/scripts/verify-package.mjs README.md README.zh-CN.md extension/README.md gateway/app/modules/task/README.md gateway/app/agents/job_match/README.md docs/superpowers/specs/2026-07-18-shared-workspace-design.md docs/superpowers/specs/2026-07-20-workspace-streaming-design.md gateway/tests extension
git commit -m "docs: release prompt shortcut workspace v4"
```

---

## Final acceptance checklist

- [ ] Protocol headers, body models, response models, NDJSON terminal payloads, Extension constant,
      and package all report version `4`.
- [ ] Quick Insight returns localized `shortcuts`; no runtime response exposes `actions` or a default
      selected Action.
- [ ] Neither UI entry calls Workspace on Shortcut click; both replace/focus the composer, including
      empty Ask More.
- [ ] Workspace submits only the edited `message` plus shared state; no Shortcut ID or Action field
      crosses the HTTP boundary.
- [ ] `JobMatchAgent` plans every message from current message, Artifacts, and history; Quick Action
      deterministic plans are gone.
- [ ] Analyze output contains exactly the two comparison columns requested by the user.
- [ ] Tailor Resume asks for a change plan before generation; later confirmation can create/update CV.
- [ ] Cover Letter creates and updates a plain-text, copyable Artifact.
- [ ] Ten canonical user sends work; an eleventh is blocked, and pending failures do not consume a turn.
- [ ] v2 local Workspace history, Attachments, Artifacts, and page metadata survive v3 migration;
      Action state is removed and v1 migration is gone.
- [ ] Full Gateway/Extension suites, import check, package check, diff check, and manual smoke test pass.
