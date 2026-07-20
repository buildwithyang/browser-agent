# Job Match Workspace Orchestration Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute this plan task by task. Use `superpowers:test-driven-development` inside every implementation task and `superpowers:verification-before-completion` before the final handoff.

**Goal:** Replace the never-deployed `DocumentContent` Workspace flow with a shared-history chat Orchestrator that returns Markdown replies or versioned CV/Cover Letter Attachments, and strictly gate Gateway/Extension compatibility with protocol version 2.

**Architecture:** `JobMatchAgent` is a Facade/Mediator over an `IntentRouter` and four Strategy specialists. `TaskService` is the state reducer that turns one typed `ChatResult` into the complete next Workspace state. Quick Insight and Workspace use separate Agent interfaces. The old `POST /tasks` route becomes a thin `426 Upgrade Required` shim and no longer executes legacy Agents. The Extension owns local state, renders Gateway Markdown with packaged Marked + DOMPurify, and applies only complete responses whose protocol version equals its own code-level protocol version.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, OpenAI-compatible chat client, pytest; Chrome MV3, JavaScript ESM, Node test runner, Marked, DOMPurify, jsdom.

---

## Fixed decisions and constraints

- Work directly on `main`, as requested. Preserve unrelated user changes.
- Read the relevant module README before changing that module; the task and Extension READMEs have already been reviewed, but re-open them if execution starts in a fresh context.
- `CURRENT_EXTENSION_PROTOCOL_VERSION = 2` is a code constant. Do not compare API compatibility with `manifest.version`.
- Send `X-Agent-Bridge-Protocol-Version: 2` on both task endpoints. Missing, invalid, or unequal values return 426 before Service/Agent execution.
- A Task protocol middleware validates before routing/auth/body parsing and adds `X-Agent-Bridge-Protocol-Version: 2` to every Task response. A 426 also carries `Upgrade: Agent-Bridge/2`.
- Successful Quick Insight and Workspace JSON both contain top-level `protocol_version: 2`; the Extension validates response Header first and then rejects a missing or unequal successful-body value.
- The update URL is Gateway Settings with the Chrome Web Store URL as default. The protocol integer is not environment-configurable.
- The Extension carries the same store URL as a fallback when an old Gateway returns no upgrade payload.
- `POST /tasks` always returns the same 426 upgrade payload. It does not parse the old document request or call a Service, Agent, Resume Service, Repository, or LLM.
- During Tasks 1–7, new chat wire types use the temporary names `WorkspaceChatRequest` / `WorkspaceChatResponse`, while the existing `WorkspaceRequest` / `WorkspaceResponse` remain runnable. Task 8 atomically switches the API and renames chat types to the final names before deleting the old types.
- Delete the old `TaskRequest`, `TaskResponse`, `DocumentContent`, `DocumentDraft`, `Section`, legacy adapter, and legacy generation paths. Keep `Insight`, typed Insight cards, `render_markdown`, Python `markdown`, and `nh3` because Quick Insight still uses them.
- Workspace output is Markdown only. Do not add `content_html`, `html`, `sections`, or `document` to the new response.
- Do not classify or blacklist Markdown content in the Gateway. The structured field and Agent prompt request Markdown; Marked + DOMPurify in the Extension own format support and sanitization, including raw HTML accepted by the Markdown library.
- Action is a strong hint for ordinary user messages; Quick Insight Analyze/Tailor/Cover actions are deterministic commands and skip `IntentRouter`. Quick Insight Ask More only opens/focuses the panel.
- All Agent objects remain stateless. Resume text, page context, histories, artifacts, and trigger are request-scoped inputs.
- There is no DB schema or Repository change. Do not modify `gateway/app/modules/task/model.py`, `repo.py`, or `deploy/initdb/001-schema.sql`.
- Release only after Extension v2 passes Chrome Web Store review in manual-publish mode; then deploy Gateway v2, immediately publish the approved Extension, and notify internal seed users. Old Extension versions cannot render the new 426 payload and will show only their generic failure UI.
- Every new/changed interface, abstract method, and function needs a concise docstring/JSDoc. Add comments around non-obvious orchestration and reducer branches.
- CV Attachment uses the fixed Gateway-returned preview URL for now. Cover Letter Attachment contains the complete Markdown snapshot. Neither artifact is persisted on the server.

## Target structure

```text
gateway/app/agents/job_match/
├── __init__.py
├── agent.py
├── context.py
├── quick_insight.py
├── router.py
├── README.md
└── specialists/
    ├── __init__.py
    ├── base.py
    ├── analysis.py
    ├── resume.py
    ├── cover_letter.py
    └── general_qa.py

gateway/app/modules/task/
├── api.py
├── protocol.py
├── schema.py
├── service.py
└── legacy/
    ├── api.py
    └── README.md

extension/
├── markdown.js
├── workspace-operation.js
├── scripts/sync-markdown-vendor.mjs
└── vendor/
    ├── marked.esm.js
    ├── purify.es.mjs
    └── THIRD_PARTY_NOTICES.md
```

## Task 1: Add protocol and Workspace v2 domain contracts

**Files:**

- Create: `gateway/app/modules/task/protocol.py`
- Modify: `gateway/app/modules/task/schema.py`
- Modify: `gateway/tests/test_task_schema.py`
- Replace assertions in: `gateway/tests/test_task_workspace_schema.py`
- Modify: `gateway/tests/test_task_v2_schema.py`

### Step 1: Write failing protocol and Workspace schema tests

Cover all of these cases:

- `CURRENT_EXTENSION_PROTOCOL_VERSION == 2` and the default store URL are stable.
- `QuickInsightResponse.protocol_version` defaults to 2.
- The request is a Pydantic discriminated union on `trigger`:
  - `user_message` requires a non-empty `message` and permits at most nine prior histories.
  - `quick_insight_action` forbids `message` and permits ten prior histories.
- Every Message has `id`, `role`, `content`, `action_id`, UTC `created_at`, and `attachments`.
- User Message attachments are empty; Assistant Message has at most one Attachment.
- `artifacts` contains exactly nullable `cv` and `cover_letter` keys.
- IDs are unique within their category; Artifact type matches the key; latest Artifact Attachment equals the last history Attachment of the same type.
- CV Attachment content is an absolute HTTP(S) URL; Cover Letter content is Markdown text.
- `WorkspaceChatResponse` requires `result_type`, full histories, full artifacts, and `protocol_version`; its JSON has no `document`, `html`, or `sections`.
- Existing character, title, version, and message-count limits from the approved spec are enforced.

Run:

```bash
(cd gateway && uv run pytest tests/test_task_schema.py tests/test_task_workspace_schema.py tests/test_task_v2_schema.py -v)
```

Expected: FAIL on missing protocol, triggers, attachments, artifacts, and new response fields.

### Step 2: Implement the typed contracts

In `protocol.py`, define and document:

```python
CURRENT_EXTENSION_PROTOCOL_VERSION = 2
EXTENSION_PROTOCOL_HEADER = "X-Agent-Bridge-Protocol-Version"
DEFAULT_EXTENSION_UPDATE_URL = (
    "https://chromewebstore.google.com/detail/agent-bridge/"
    "cmajoaedbjinocbfdkebaedkdbkhbhai"
)
```

In `schema.py`, add StrEnums/Literals and Pydantic models for:

- `WorkspaceTrigger`
- `WorkspaceResultType`
- `ArtifactType`
- `Attachment`
- `Artifact`
- fixed-key `Artifacts`
- `ReplyResult`
- `CreateArtifactResult`
- `UpdateArtifactResult`
- discriminated `ChatResult`
- `UserMessageWorkspaceRequest`
- `QuickInsightActionWorkspaceRequest`
- discriminated `WorkspaceChatRequest`
- Markdown-only `WorkspaceChatResponse`

Put the cross-object invariants in one documented validation helper reused by both request variants and the response. Reject extra fields so an old `currentDocument` or `document` cannot pass silently. Keep the existing runtime `WorkspaceRequest` and `WorkspaceResponse` names unchanged in this task; they are deleted and the chat types receive the final names in Task 8.

Delete old document-only schemas only after all references are migrated in Task 8; during Task 1, mark them as transitional if needed to keep the repository importable.

### Step 3: Run targeted tests

```bash
(cd gateway && uv run pytest tests/test_task_schema.py tests/test_task_workspace_schema.py tests/test_task_v2_schema.py -v)
```

Expected: PASS.

### Step 4: Commit

```bash
git add gateway/app/modules/task/protocol.py gateway/app/modules/task/schema.py gateway/tests/test_task_schema.py gateway/tests/test_task_workspace_schema.py gateway/tests/test_task_v2_schema.py
git commit -m "feat: define workspace chat protocol"
```

## Task 2: Separate Quick Insight and Workspace Agent interfaces

**Files:**

- Modify: `gateway/app/agents/base.py`
- Modify: `gateway/app/agents/summary_page.py`
- Modify: `gateway/tests/test_summary_page.py`
- Modify: `gateway/tests/test_language.py`
- Modify: `gateway/tests/test_routing.py`

### Step 1: Write failing interface and Summary Page tests

Tests must prove:

- Quick Insight calls `quick_insight()` and `available_actions()`.
- Workspace calls `handle_chat()` and returns `ReplyResult` Markdown.
- `SummaryPageAgent.handle_chat()` accepts only `ask_more`.
- No new Workspace API depends on `execute() -> DocumentContent`.
- Language directives still apply to both paths.

Run:

```bash
(cd gateway && uv run pytest tests/test_summary_page.py tests/test_language.py tests/test_routing.py -v)
```

Expected: FAIL because `TaskAgent` still conflates all operations.

### Step 2: Add explicit abstract contracts beside the transitional contract

Add the documented abstractions below. Keep the existing `TaskAgent`, `actions()`, `insight()`, and `execute()` contract temporarily so `TaskService`, `main.py`, and the still-live `/tasks` route remain importable until the atomic cleanup in Task 8:

```python
class QuickInsightAgent(ABC):
    @abstractmethod
    def quick_insight(self, context: AgentContext) -> AgentExecution[Insight]:
        """Generate the typed decision-first insight for the current page."""
        raise NotImplementedError

    @abstractmethod
    def available_actions(self, context: AgentContext) -> list[Action]:
        """Return actions supported by the routed page Agent."""
        raise NotImplementedError


class WorkspaceAgent(ABC):
    @abstractmethod
    def handle_chat(
        self, context: WorkspaceAgentContext
    ) -> AgentExecution[ChatResult]:
        """Handle one immutable Workspace chat context."""
        raise NotImplementedError
```

Keep OpenAI client/model routing reusable. During Tasks 2–7, `OpenAIChatAgent` may still inherit the transitional `TaskAgent`; Task 8 removes that inheritance and the old abstract methods after all consumers have migrated. Use request-scoped immutable context dataclasses. Change `format_workspace_context()` to format the optional current message, selected Action, full histories, artifacts, and page context without assuming every trigger has a `message`.

Update `SummaryPageAgent` to implement both explicit operations and to return only `ReplyResult` from the new Workspace path. Keep its old `execute()` implementation only as a temporary `/tasks` bridge and delete it in Task 8.

### Step 3: Run targeted tests and commit

```bash
(cd gateway && uv run pytest tests/test_summary_page.py tests/test_language.py tests/test_routing.py -v)
git add gateway/app/agents/base.py gateway/app/agents/summary_page.py gateway/tests/test_summary_page.py gateway/tests/test_language.py gateway/tests/test_routing.py
git commit -m "refactor: separate task agent operations"
```

## Task 3: Convert Job Match into a package and preserve Quick Insight

**Files:**

- Delete: `gateway/app/agents/job_match.py`
- Create: `gateway/app/agents/job_match/__init__.py`
- Create: `gateway/app/agents/job_match/agent.py`
- Create: `gateway/app/agents/job_match/context.py`
- Create: `gateway/app/agents/job_match/quick_insight.py`
- Create temporarily: `gateway/app/agents/job_match/legacy.py`
- Create: `gateway/app/agents/job_match/specialists/__init__.py`
- Modify: `gateway/tests/test_job_match.py`
- Modify: `gateway/tests/test_task_router.py`

### Step 1: Refocus existing tests on Quick Insight

Keep and strengthen score, recommendation, overview, strength, gap, invalid JSON, short-JD validation, Action list, and LinkedIn/Indeed routing tests. Remove assertions that an Action directly returns a `DocumentContent`.

Add import-surface assertions that these continue to work:

```python
from app.agents.job_match import JobMatchAgent, MIN_JOB_CONTENT_CHARS
```

Run:

```bash
(cd gateway && uv run pytest tests/test_job_match.py tests/test_task_router.py -v)
```

Expected: tests define the desired package surface before the file-to-directory replacement.

### Step 2: Perform the atomic file-to-package replacement

Move Quick Insight parsing/prompt logic into `quick_insight.py`. `JobMatchAgent` delegates Quick Insight and declares the same name, resume requirement, and Actions. Move the old document prompt, section parser, and `execute()` implementation without behavior changes into a temporary `legacy.py`, then delegate the transitional `JobMatchAgent.execute()` to it. This is not part of the final architecture: Task 8 deletes the file and delegation at the same time `/tasks` becomes a 426 shim. Never carry the `_cv_text` cross-request cache; legacy execution must use request-scoped `ctx.resume_text`.

Define immutable `JobChatContext` in `context.py` with the trigger, request, resume text, histories, artifacts, selected Action, and optional current message. Do not store any of these on the Agent instance. Add a regression test proving the temporary legacy delegate still returns the old response until Task 8 removes the endpoint.

### Step 3: Run targeted tests and commit

```bash
(cd gateway && uv run pytest tests/test_job_match.py tests/test_task_router.py -v)
(cd gateway && uv run python -c "from app.agents.job_match import JobMatchAgent; print(JobMatchAgent.__name__)")
git add gateway/app/agents/job_match.py gateway/app/agents/job_match gateway/tests/test_job_match.py gateway/tests/test_task_router.py
git commit -m "refactor: package job match agent"
```

## Task 4: Implement the four Specialist Strategies

**Files:**

- Create: `gateway/app/agents/job_match/specialists/base.py`
- Create: `gateway/app/agents/job_match/specialists/analysis.py`
- Create: `gateway/app/agents/job_match/specialists/resume.py`
- Create: `gateway/app/agents/job_match/specialists/cover_letter.py`
- Create: `gateway/app/agents/job_match/specialists/general_qa.py`
- Create: `gateway/tests/test_job_match_specialists.py`

### Step 1: Write failing result-matrix tests

Test structured parsing, language directives, full context inclusion, and this legal matrix:

| Specialist | reply | artifact draft |
| --- | --- | --- |
| JobAnalysisAgent | yes | no |
| ResumeTailoringAgent | yes | CV only |
| CoverLetterAgent | yes | Cover Letter only |
| GeneralQAAgent | yes | no |

Resume/Cover Letter questions such as “what should I emphasize?” must return reply. Explicit create/rewrite instructions may return a complete artifact draft. A draft is full Markdown, never a partial patch or HTML.

Run:

```bash
(cd gateway && uv run pytest tests/test_job_match_specialists.py -v)
```

Expected: FAIL because the Strategy interface and specialists do not exist.

### Step 2: Implement the Strategy interface and specialists

Define documented `SpecialistReply`, `ArtifactDraftResult`, and their discriminated union. Parse one structured JSON object from each Specialist. Reject missing fields, wrong artifact types, or results outside the legal matrix. Require non-empty Markdown strings, but do not inspect tag syntax, maintain a Markdown whitelist, or reject content accepted by the selected Markdown library; rendering and sanitization belong to the Extension.

Specialists may share prompt-formatting helpers but must own their scenario instructions. They must call only the injected OpenAI-compatible client and remain stateless.

### Step 3: Run tests and commit

```bash
(cd gateway && uv run pytest tests/test_job_match_specialists.py -v)
git add gateway/app/agents/job_match/specialists gateway/tests/test_job_match_specialists.py
git commit -m "feat: add job match specialist agents"
```

## Task 5: Implement IntentRouter

**Files:**

- Create: `gateway/app/agents/job_match/router.py`
- Create: `gateway/tests/test_job_match_router.py`

### Step 1: Write failing router tests

Cover:

- current user message outranks selected Action;
- selected Action outranks ambiguous history;
- history informs follow-up pronouns and “rewrite the previous one”;
- fallback is GeneralQA only when the model returns a valid GeneralQA decision;
- first invalid structured output triggers exactly one repair call;
- the second invalid output raises a typed routing error rather than silently routing GeneralQA;
- Quick Insight command paths do not invoke the Router.

Run:

```bash
(cd gateway && uv run pytest tests/test_job_match_router.py -v)
```

Expected: FAIL because `IntentRouter` does not exist.

### Step 2: Implement structured routing

Define `SpecialistId` and `RouteDecision`. The Router prompt explicitly states the priority `message > Action > history` and returns only a structured specialist identifier. Keep it free of response generation and artifact decisions.

On parse failure, make one repair call using the invalid output and schema requirements. Raise a documented `IntentRoutingError` after the second failure.

### Step 3: Run tests and commit

```bash
(cd gateway && uv run pytest tests/test_job_match_router.py -v)
git add gateway/app/agents/job_match/router.py gateway/tests/test_job_match_router.py
git commit -m "feat: route job workspace intent"
```

## Task 6: Implement JobMatchAgent orchestration

**Files:**

- Modify: `gateway/app/agents/job_match/agent.py`
- Modify: `gateway/app/agents/job_match/__init__.py`
- Create: `gateway/tests/test_job_match_orchestrator.py`

### Step 1: Write failing Facade/Mediator tests

Test ordinary user-message orchestration and deterministic Quick Insight commands:

- normal message invokes Router then exactly one Specialist;
- selected Action is a hint and does not force an artifact;
- Analyze maps directly to JobAnalysis reply;
- Tailor Resume maps directly to a CV draft;
- Generate Cover Letter maps directly to a Cover Letter draft;
- Ask More is rejected as a backend Quick Action because the Extension should not send it;
- Quick commands never invoke Router;
- existing type artifact becomes `update_artifact`; absent type becomes `create_artifact`;
- the other artifact is irrelevant to create/update choice;
- illegal Specialist result/type raises an orchestration error;
- `AgentExecution.model` reports the final Specialist model.

Run:

```bash
(cd gateway && uv run pytest tests/test_job_match_orchestrator.py -v)
```

Expected: FAIL until `handle_chat()` coordinates the components.

### Step 2: Implement the Facade/Mediator

Inject Router and Specialist map into `JobMatchAgent` with production defaults and test fakes. Convert a legal `ArtifactDraftResult` to `CreateArtifactResult` or `UpdateArtifactResult` based only on `context.artifacts[artifact_type]`. Return `ReplyResult` unchanged.

Validate deterministic Quick Action output against the stricter matrix before returning. Do not allocate Message/Attachment/Artifact IDs here.

### Step 3: Run tests and commit

```bash
(cd gateway && uv run pytest tests/test_job_match_orchestrator.py tests/test_job_match.py -v)
git add gateway/app/agents/job_match gateway/tests/test_job_match_orchestrator.py
git commit -m "feat: orchestrate job workspace chat"
```

## Task 7: Replace TaskService document flow with the state reducer

**Files:**

- Modify: `gateway/app/modules/task/service.py`
- Create: `gateway/tests/test_task_workspace_service.py`
- Modify: `gateway/tests/test_task_v2_service.py`
- Modify: `gateway/tests/test_task_rate_limit.py`

### Step 1: Write failing reducer tests

Use fake Workspace Agents and fixed UUID/time providers where necessary. Cover:

- `user_message` appends one User and one Assistant Message;
- `quick_insight_action` appends only one Assistant Message;
- reply leaves both artifacts byte-for-byte unchanged;
- create allocates Artifact ID, Attachment ID, version 1, UTC time, and one Attachment;
- update reuses Artifact ID, increments version once, and appends a new immutable Attachment;
- CV and Cover Letter coexist; updating one does not mutate the other;
- Cover Letter Attachment stores the complete Markdown snapshot;
- CV Attachment URL comes from the Gateway-owned fixed preview setting/constant, not client state;
- invalid Agent result and model failure produce no partial next state;
- rate limit, resume injection, metrics persistence, and URL normalization still work;
- `meta.duration_ms` measures the complete Router + Specialist call because Service times the whole `handle_chat()` operation;
- 9 histories + current user input succeeds and returns 11; 10 + user is rejected; 10 + Quick Action succeeds.

Run:

```bash
(cd gateway && uv run pytest tests/test_task_workspace_service.py tests/test_task_v2_service.py tests/test_task_rate_limit.py -v)
```

Expected: FAIL because Service still calls `execute()` and returns `document`.

### Step 2: Implement one pure transition helper and Service orchestration

Create a documented private reducer that accepts validated prior state plus `ChatResult` and returns new histories/artifacts in memory. Allocate IDs and time only after Agent success. During this staged task, add `TaskService.workspace_chat()` accepting `WorkspaceChatRequest` and returning `WorkspaceChatResponse`; keep the existing `workspace()` method runnable until Task 8 switches the API.

Keep Service free of HTTP status/version-header handling. Keep Repository usage limited to existing operational metrics. Remove `TaskService.execute()` once Task 8 has changed `/tasks` to the 426 shim.

### Step 3: Run tests and commit

```bash
(cd gateway && uv run pytest tests/test_task_workspace_service.py tests/test_task_v2_service.py tests/test_task_rate_limit.py -v)
git add gateway/app/modules/task/service.py gateway/tests/test_task_workspace_service.py gateway/tests/test_task_v2_service.py gateway/tests/test_task_rate_limit.py
git commit -m "feat: reduce workspace chat state"
```

## Task 8: Integrate task APIs, strict protocol gate, and legacy 426 shim

**Files:**

- Modify: `gateway/app/config.py`
- Modify: `gateway/.env.example`
- Modify: `gateway/app/modules/task/api.py`
- Modify: `gateway/app/modules/task/legacy/api.py`
- Delete: `gateway/app/modules/task/legacy/adapter.py`
- Delete: `gateway/app/modules/task/legacy/schema.py`
- Modify: `gateway/app/modules/task/legacy/__init__.py`
- Delete: `gateway/app/agents/job_match/legacy.py`
- Modify: `gateway/app/main.py`
- Create: `gateway/tests/test_task_protocol.py`
- Modify: `gateway/tests/test_task_workspace_api.py`
- Modify: `gateway/tests/test_task_v2_api.py`
- Replace: `gateway/tests/test_task_legacy_api.py`
- Modify: `gateway/tests/test_tasks_auth.py`
- Modify: `gateway/tests/test_task_input_caps.py`
- Modify: `gateway/tests/test_tasks_api.py`

### Step 1: Write failing API/version tests

Test all boundaries:

- Quick Insight and Workspace without the protocol Header return 426 before routing, auth, body validation, or fake Service execution.
- malformed and unequal protocol values return 426.
- matching version reaches Service; every response contains the protocol Header; success JSON includes `protocol_version: 2`.
- 426 contains a stable error code, required version, configured update URL, protocol response Header, and `Upgrade: Agent-Bridge/2`.
- protocol validation precedes authentication; matching-version 401/429/502 responses still carry the protocol response Header.
- CORS `OPTIONS` preflight is never gated and advertises the custom request/response Header.
- Workspace request/response contains trigger, histories, artifacts, result type, and no old document fields.
- `POST /tasks` returns 426 for empty, invalid, and old-shape JSON and never resolves TaskService.
- public requests still cannot select an internal Agent.

Use one direct protocol-middleware JSON shape consistently:

```json
{
  "code": "extension_update_required",
  "message": "Extension update required",
  "required_protocol_version": 2,
  "update_url": "https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai"
}
```

Run:

```bash
(cd gateway && uv run pytest tests/test_task_protocol.py tests/test_task_workspace_api.py tests/test_task_v2_api.py tests/test_task_legacy_api.py tests/test_tasks_auth.py tests/test_task_input_caps.py -v)
```

Expected: FAIL until API validation and the shim exist.

### Step 2: Implement the Task protocol middleware

Add `extension_update_url` to `Settings` and `.env.example`; keep the protocol integer in `protocol.py`. In `protocol.py`, add a documented ASGI/Starlette middleware and one `upgrade_required_response()` factory.

For `POST /tasks/quick-insight` and `POST /tasks/workspace`, the middleware parses the raw Header string before the router sees the request. Empty, non-integer, negative, oversized, missing, and unequal values return the direct 426 JSON. Matching requests continue and receive the protocol response Header even when the inner endpoint returns 401/400/429/502. Non-POST methods and every `OPTIONS` preflight pass through without a protocol requirement.

Register middleware in this execution order: `CORS -> TaskProtocolMiddleware -> CookieSessionMiddleware -> Router`. With Starlette's reverse wrapping, call `add_middleware()` for Session first, Task Protocol second, and CORS last. Expose `X-Agent-Bridge-Protocol-Version` through CORS and allow it in preflight. Keep successful response-model defaults at version 2.

Intercept exact `POST /tasks` in the middleware and return 426 without reading the body. Keep `legacy/api.py` as a raw-`Request` fallback route that returns the same response and never declares a Pydantic body model. This guarantees empty, malformed, or oversized old JSON cannot become 422 before the upgrade response.

### Step 3: Delete the unused document execution graph

Switch `/tasks/workspace` from the old `workspace()` method to `workspace_chat()`, then delete the old method and rename `workspace_chat()` to the final `workspace()` name. Rename `WorkspaceChatRequest` / `WorkspaceChatResponse` to the final `WorkspaceRequest` / `WorkspaceResponse` names at the same boundary. Remove legacy adapter/schema imports, `TaskService.execute()`, old document schemas, old `TaskAgent.execute()`, document prompt/parser code, and obsolete tests. Update `main.py` Agent registry typing/assembly for the two explicit interfaces. Do not remove Quick Insight HTML rendering dependencies.

### Step 4: Run Gateway tests and commit

```bash
(cd gateway && uv run pytest tests/test_task_protocol.py tests/test_task_workspace_api.py tests/test_task_v2_api.py tests/test_task_legacy_api.py tests/test_tasks_auth.py tests/test_task_input_caps.py tests/test_tasks_api.py -v)
(cd gateway && uv run pytest -q)
(cd gateway && uv run python -c "import app.main; print('main import ok')")
git add gateway/.env.example gateway/app/config.py gateway/app/main.py \
  gateway/app/modules/task/api.py gateway/app/modules/task/protocol.py \
  gateway/app/modules/task/schema.py gateway/app/modules/task/service.py \
  gateway/app/modules/task/legacy gateway/app/agents/base.py \
  gateway/app/agents/summary_page.py gateway/app/agents/job_match \
  gateway/tests/test_task_workspace_api.py gateway/tests/test_task_v2_api.py \
  gateway/tests/test_task_protocol.py \
  gateway/tests/test_task_legacy_api.py gateway/tests/test_tasks_auth.py \
  gateway/tests/test_task_input_caps.py gateway/tests/test_tasks_api.py
git commit -m "feat: gate extension task protocol"
```

Expected: all Gateway tests PASS.

## Task 9: Add Extension protocol validation and Workspace v2 state

**Files:**

- Modify: `extension/config.js`
- Modify: `extension/config.test.js`
- Modify: `extension/auth.js`
- Modify: `extension/auth.test.js`
- Modify: `extension/workspace.js`
- Replace assertions in: `extension/workspace.test.js`
- Modify: `extension/workspace-controller.js`
- Modify: `extension/workspace-controller.test.js`

### Step 1: Write failing protocol/state tests

Cover:

- `EXTENSION_PROTOCOL_VERSION === 2` is independent of `manifest.version`, and the Extension has a store URL fallback.
- `buildAuthHeaders()` always includes `X-Agent-Bridge-Protocol-Version: 2` and conditionally includes Bearer auth.
- `buildWorkspaceBody()` emits the correct trigger union, full histories, and fixed-key artifacts; it never sends `currentDocument`.
- `readGatewayResponse()` validates the response Header before handling any status, then throws `ExtensionUpdateRequiredError` for 426, a missing/unequal Header, a missing successful body version, or an unequal body version.
- the upgrade error carries update URL and required version and is not treated as a 401/token-clear event.
- schema v2 validates IDs, timestamps, attachments, artifacts, latest-snapshot consistency, and both message-count rules.
- `applyWorkspaceResponse()` validates the complete response and atomically replaces histories/artifacts; any invalid response leaves the caller's prior object unchanged.

Run:

```bash
(cd extension && node --test config.test.js auth.test.js workspace.test.js workspace-controller.test.js)
```

Expected: FAIL on protocol and v2 fields.

### Step 2: Implement the protocol client and state model

Export the protocol constant/header and store fallback URL from `config.js`. Update request builders in `auth.js`. In `workspace-controller.js`, add a documented `ExtensionUpdateRequiredError`; parse the direct 426 body, response Header, and successful top-level version. Protocol incompatibility must be detected before a 401 can trigger token clearing.

Replace `currentDocument` with:

```js
artifacts: { cv: null, cover_letter: null }
```

Add `schemaVersion: 2`, `canSendUserMessage()`, and `canRunQuickInsightAction()`. Keep state validation pure and avoid local optimistic Message appends.

### Step 3: Implement safe v1-to-v2 local migration

Use a v2 owner/resource storage key. When an active tab mapping points to v1:

1. load but do not remove the v1 value;
2. retain valid messages and add `attachments: []` where missing;
3. remove `currentDocument`, initialize empty artifacts, and preserve Quick Insight/Actions/selection;
4. write and re-read the v2 value;
5. update the tab mapping to v2;
6. only then remove the v1 value.

If any write/read step fails, leave the v1 value and old mapping untouched. Add tests for success and failed-write preservation.

### Step 4: Run tests and commit

```bash
(cd extension && node --test config.test.js auth.test.js workspace.test.js workspace-controller.test.js)
git add extension/config.js extension/config.test.js extension/auth.js extension/auth.test.js extension/workspace.js extension/workspace.test.js extension/workspace-controller.js extension/workspace-controller.test.js
git commit -m "feat: version extension workspace protocol"
```

## Task 10: Execute Quick Insight Actions through the shared Workspace queue

**Files:**

- Create: `extension/workspace-operation.js`
- Create: `extension/workspace-operation.test.js`
- Modify: `extension/background.js`
- Modify: `extension/quick-insight.js`
- Modify: `extension/quick-insight.test.js`
- Modify: `extension/workspace-controller.test.js`

### Step 1: Write failing orchestration tests

Test this pure mapping and side effects:

- Analyze/Tailor Resume/Generate Cover Letter map to `quick_insight_action` and issue one Workspace request.
- Ask More only opens/focuses the Side Panel and issues no Workspace request.
- quick actions seed/open the Workspace before the asynchronous request starts.
- they reload the latest state inside the existing per-resource queue and carry histories/artifacts.
- they restore the URL-bound right-click JD selection when fresh page selection is empty.
- success applies the whole response; no fake User Message is appended.
- normal composer send uses `user_message` through the same queue.
- 426/missing-version errors keep state and broadcast a structured update-required event with URL.
- ordinary errors keep state and broadcast a retryable composer error.
- owner changes discard late responses; a late 401 still follows the existing token snapshot rule.

Run:

```bash
(cd extension && node --test workspace-operation.test.js quick-insight.test.js workspace-controller.test.js)
```

Expected: FAIL because Quick Insight actions currently only seed/open the panel.

### Step 2: Implement the command mapping and background flow

Keep `workspace-operation.js` free of Chrome globals. In `background.js`, reuse the existing keyed queue, page-context collection, owner snapshot, fetch, response reader, atomic state write, and broadcasts. Do not duplicate a second fetch/state pipeline for Quick Insight.

Update Quick Insight error presentation so an upgrade-required response links to the store instead of displaying a generic retry error.

### Step 3: Run tests and commit

```bash
(cd extension && node --test workspace-operation.test.js quick-insight.test.js workspace-controller.test.js)
git add extension/workspace-operation.js extension/workspace-operation.test.js extension/background.js extension/quick-insight.js extension/quick-insight.test.js extension/workspace-controller.test.js
git commit -m "feat: execute quick insight workspace actions"
```

## Task 11: Package and verify Markdown rendering

**Files:**

- Modify: `extension/package.json`
- Create: `extension/package-lock.json`
- Create: `extension/scripts/sync-markdown-vendor.mjs`
- Create: `extension/vendor/marked.esm.js`
- Create: `extension/vendor/purify.es.mjs`
- Create: `extension/vendor/THIRD_PARTY_NOTICES.md`
- Create: `extension/markdown.js`
- Create: `extension/markdown.test.js`
- Modify: `extension/package.sh`

### Step 1: Write failing renderer and package tests

Use jsdom to test headings, bold, italic, ordered/unordered lists, links, inline code, code blocks, and GFM tables. Verify DOMPurify removes executable markup/attributes produced from raw Markdown input. Verify the packaged zip contains renderer/vendor files, excludes `node_modules`, has no CDN URL, and every Side Panel import resolves.

Run:

```bash
(cd extension && npm install)
(cd extension && node --test markdown.test.js)
(cd extension && npm run test:package)
```

Expected: FAIL because dependencies and packaged vendor files do not exist.

### Step 2: Add locked dependencies and committed vendor assets

Add Marked and DOMPurify runtime dependencies plus jsdom for tests. The sync script copies:

- `node_modules/marked/lib/marked.esm.js` -> `vendor/marked.esm.js`
- `node_modules/dompurify/dist/purify.es.mjs` -> `vendor/purify.es.mjs`

Commit the generated vendor files so “Load unpacked” works without running npm first. `markdown.js` exports one documented `renderMarkdown(markdown, windowRef)` function that runs Marked then DOMPurify before returning HTML.

Add `markdown.js` and `vendor/` to the packaging allowlist. Do not load CDN resources.

### Step 3: Run tests and commit

```bash
(cd extension && npm install)
(cd extension && node --test markdown.test.js)
(cd extension && npm run test:package)
git add extension/package.json extension/package-lock.json extension/scripts extension/vendor extension/markdown.js extension/markdown.test.js extension/package.sh
git commit -m "feat: bundle workspace markdown renderer"
```

## Task 12: Simplify Side Panel to classic chat with inline Attachments

**Files:**

- Modify: `extension/sidepanel.html`
- Modify: `extension/sidepanel.css`
- Modify: `extension/sidepanel.js`
- Replace assertions in: `extension/sidepanel.test.js`

### Step 1: Write failing UI behavior tests

Test:

- header shows job title/source and match score only;
- Business Overview, Role Focus, Strength, Gap, Quick Insight card, and Latest Artifact region are absent;
- User messages use text content; Assistant messages use sanitized Markdown;
- no “You/你/Agent” sender labels appear;
- every Message displays local `HH:mm` and full local datetime tooltip;
- Attachment renders inside its Assistant Message;
- Cover Letter renders Markdown and copies the original Markdown string;
- CV uses the response URL and never a UI hard-coded URL;
- Action chips wrap beside the sticky composer and switching does not clear history;
- table and code containers scroll locally while the panel has no page-level horizontal overflow;
- update-required composer state shows a store link, says to check Gateway deployment if the error persists after updating, and does not masquerade as login expiry;
- generic pages expose only Ask More.

Run:

```bash
(cd extension && node --test sidepanel.test.js markdown.test.js workspace.test.js)
```

Expected: FAIL against the current Quick Insight/document layout.

### Step 2: Implement the classic chat layout

Render chronological histories as the only main content. Keep a compact light-theme header and sticky composer. Render Attachment under the same Assistant bubble. Use `textContent` for User content and the sanitized renderer for Assistant/Cover Letter Markdown. Use `Intl.DateTimeFormat` for visible time and `Date` for the tooltip.

Render structured update-required and ordinary retry errors near the composer. Preserve keyboard behavior: Enter sends; Shift+Enter adds a new line.

### Step 3: Run tests and commit

```bash
(cd extension && node --test sidepanel.test.js markdown.test.js workspace.test.js)
git add extension/sidepanel.html extension/sidepanel.css extension/sidepanel.js extension/sidepanel.test.js
git commit -m "feat: render classic workspace chat"
```

## Task 13: Update architecture/user documentation and run full verification

**Files:**

- Create: `gateway/app/agents/job_match/README.md`
- Modify: `gateway/app/modules/task/README.md`
- Modify: `gateway/app/modules/task/legacy/README.md`
- Modify: `extension/README.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/superpowers/specs/2026-07-19-job-match-workspace-orchestration-design.md`

### Step 1: Update documentation to the final code, not the discarded design

Document:

- `JobMatchAgent` Facade/Mediator and four Strategy specialists;
- message > Action > history routing priority;
- Quick Action deterministic path;
- reply/create/update result matrix;
- shared histories, fixed-key artifacts, and Attachment snapshots;
- protocol version 2 request Header, response field, 426 behavior, and update URL;
- `/tasks` is an upgrade shim, not a legacy generation API;
- Workspace is Markdown-only while Quick Insight still uses typed cards/server-rendered safe HTML;
- local v1-to-v2 migration and 10-message input rules;
- no server Thread/Artifact persistence in this release.

Remove all user-facing claims that the current Workspace returns `DocumentContent`, sections, a single latest document, or server HTML.

Mark the spec status as implemented only after all verification succeeds.

### Step 2: Run targeted contract searches

```bash
rg -n "currentDocument|DocumentContent|TaskService\.execute|LegacyJobMatchAgent|content_html" gateway/app extension README.md README.zh-CN.md gateway/app/modules/task/README.md extension/README.md
rg -n "protocol_version|X-Agent-Bridge-Protocol-Version|extension_update_required" gateway/app extension gateway/tests extension/*.test.js
```

Expected: the first command finds no active Workspace/legacy-generation code; any remaining mention must explicitly describe removed history or Quick Insight-only HTML. The second command finds both runtime and test coverage.

### Step 3: Run complete verification

```bash
(cd gateway && uv run pytest)
(cd gateway && uv run python -c "import app.main; print('main import ok')")
(cd extension && npm test)
(cd extension && npm run test:package)
(cd extension && npm run package)
git diff --check
git status --short
```

Expected:

- all Gateway tests pass;
- `app.main` imports;
- all Extension tests and package checks pass;
- the production zip builds with local vendor assets and no CDN dependency;
- no whitespace errors;
- only intentional project changes remain.

### Step 4: Commit documentation and final cleanup

```bash
git add README.md README.zh-CN.md gateway/app/agents/job_match/README.md gateway/app/modules/task/README.md gateway/app/modules/task/legacy/README.md extension/README.md docs/superpowers/specs/2026-07-19-job-match-workspace-orchestration-design.md
git commit -m "docs: describe orchestrated workspace protocol"
```

## Final manual checks

The user will perform browser verification. Hand off this short checklist:

1. Reload the unpacked Extension after code changes.
2. Right-click a LinkedIn/Indeed job and verify Quick Insight score/Actions.
3. Click Analyze and confirm the panel opens with one Assistant reply and no fake User message.
4. Click Tailor Resume and confirm a CV Attachment appears using the Gateway URL.
5. Ask a resume question and confirm it replies without creating a CV version.
6. Explicitly ask to generate/rewrite the resume and confirm create/update behavior.
7. Generate and revise a Cover Letter and confirm both historical snapshots remain visible/copyable.
8. Set the local Extension protocol constant to a mismatched value, reload, and confirm the update link appears while auth and Workspace state remain intact.
9. Restore protocol version 2 before final packaging.
10. After deployment, inspect `https://browser.buildwithyang.com/api/tasks/quick-insight` through the real reverse proxy: no/wrong Header must return 426; a v2 request and every error response must preserve `X-Agent-Bridge-Protocol-Version: 2`.
