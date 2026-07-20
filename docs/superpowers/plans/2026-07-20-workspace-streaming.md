# Workspace Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream ordinary Workspace Assistant Markdown to the Chrome Side Panel while keeping the final histories and artifacts transition atomic.

**Architecture:** Protocol v3 keeps `POST /tasks/workspace` but changes its successful representation to an NDJSON event stream. Stateless Agents yield typed internal stream events; `TaskService` owns wire identity, sequencing, metrics, reduction, and the terminal complete state. Extension Background parses network events, broadcasts cumulative snapshots, and persists only the validated terminal response.

**Tech Stack:** Python 3.11+, FastAPI/Starlette `StreamingResponse`, Pydantic v2, `AsyncOpenAI.chat.completions`, NDJSON, Chrome Manifest V3 service worker APIs, Fetch `ReadableStream`, Marked, DOMPurify, Node test runner, pytest.

## Global Constraints

- Use Chat Completions only; do not add OpenAI Responses API support or a provider API selector.
- Quick Insight remains non-streaming JSON; Workspace becomes NDJSON under wire protocol version `3`.
- Keep Chrome Workspace storage schema version `2`; final histories/artifacts are unchanged.
- Stream only ordinary reply Markdown; CV and Cover Letter expose status and a terminal Attachment only.
- Never persist or log individual deltas or partial Artifact drafts.
- Preserve the existing per-owner, per-resource queue and final state validation.
- Every new Interface, Protocol, abstract method, and function receives a concise docstring/JSDoc.
- Gateway layering remains API -> Service -> Repository -> DB; streaming HTTP details stay in `api.py`.
- Do not add a stop-generation control, server Thread, Artifact Repository, SSE, WebSocket, or polling.
- Keep SQLite and PostgreSQL schemas unchanged; this feature adds no database columns.
- Execute and commit directly on the current normal `main` checkout, matching the user's local-test workflow.

---

## File map

### Gateway

- Create `gateway/app/modules/task/stream_schema.py`: protocol-v3 wire event union and NDJSON encoder.
- Create `gateway/app/agents/stream.py`: provider-independent model stream and Agent stream event types.
- Create `gateway/app/agents/job_match/planner.py`: async `ChatPlanner` and strict `ChatPlan`.
- Delete `gateway/app/agents/job_match/router.py`: superseded by `planner.py`.
- Modify `gateway/app/agents/base.py`: async client cache, completion, stream opening, and streaming Agent Protocol.
- Modify `gateway/app/agents/job_match/agent.py`: orchestrate plans, statuses, deltas, and terminal `ChatResult`.
- Modify `gateway/app/agents/job_match/specialists/*.py`: raw Markdown stream Strategies.
- Modify `gateway/app/agents/summary_page.py`: reply-only Workspace stream.
- Modify `gateway/app/modules/task/schema.py`: request `operationId` and protocol-v3 terminal response.
- Modify `gateway/app/modules/task/protocol.py`: wire version `3`.
- Modify `gateway/app/modules/task/service.py`: prepared stream, event mapping, atomic reducer, and stream metrics.
- Modify `gateway/app/modules/task/api.py`: NDJSON `StreamingResponse` and disconnect handling.

### Extension

- Create `extension/workspace-stream.js`: protocol header checks, NDJSON parsing, and event validation.
- Create `extension/workspace-stream.test.js`: transport boundary tests.
- Modify `extension/config.js`: protocol version `3`.
- Modify `extension/auth.js`: `operationId` and Workspace `Accept` header.
- Modify `extension/workspace-operation.js`: operation IDs and event callback pipeline.
- Modify `extension/background.js`: active stream coordinator, cumulative snapshots, abort, and final apply.
- Modify `extension/sidepanel.js`: optimistic transient turn and incremental rendering.
- Modify `extension/sidepanel.css`: pending, status, and failed-turn presentation.
- Modify existing Extension tests and package verification for the new runtime module.

### Deployment and documentation

- Modify `deploy/nginx.conf`: disable Workspace proxy buffering.
- Modify `gateway/app/modules/task/README.md`, `gateway/app/agents/job_match/README.md`, and `extension/README.md`.
- Modify deployment documentation to describe the unbuffered Workspace route.

---

### Task 1: Define protocol-v3 request identity and NDJSON wire events

**Files:**
- Create: `gateway/app/modules/task/stream_schema.py`
- Create: `gateway/tests/test_task_workspace_stream_schema.py`
- Modify: `gateway/app/modules/task/schema.py`
- Modify: `gateway/app/modules/task/protocol.py`
- Modify: `gateway/tests/test_task_protocol.py`
- Modify: `gateway/tests/test_task_workspace_schema.py`
- Modify: `gateway/tests/test_job_match.py`
- Modify: `gateway/tests/test_job_match_orchestrator.py`
- Modify: `gateway/tests/test_job_match_router.py`
- Modify: `gateway/tests/test_job_match_specialists.py`
- Modify: `gateway/tests/test_language.py`
- Modify: `gateway/tests/test_summary_page.py`
- Modify: `gateway/tests/test_task_rate_limit.py`
- Modify: `gateway/tests/test_task_schema.py`
- Modify: `gateway/tests/test_task_workspace_api.py`
- Modify: `gateway/tests/test_task_workspace_service.py`

**Interfaces:**
- Produces: `WorkspaceStreamEvent`, `WorkspaceStartedEvent`, `WorkspaceStatusEvent`, `WorkspaceDeltaEvent`, `WorkspaceCompletedEvent`, `WorkspaceFailedEvent`, `WorkspaceStreamStage`, and `encode_stream_event(event) -> bytes`.
- Produces: `WorkspaceRequestBase.operation_id: UUID` populated from JSON `operationId`.
- Consumes: existing `WorkspaceResponse`, `ArtifactType`, and `CURRENT_EXTENSION_PROTOCOL_VERSION`.

- [ ] **Step 1: Write failing schema and protocol tests**

Add tests that assert protocol version `3`, require `operationId`, reject unknown event fields,
enforce monotonically representable non-negative sequences, and encode one JSON line:

```python
def workspace_payload() -> dict[str, object]:
    """Build one valid Workspace request except for the operation ID under test."""

    return {
        "trigger": "user_message",
        "url": "https://example.com/article",
        "resourceUrl": "https://example.com/article",
        "actionId": "ask_more",
        "histories": [],
        "artifacts": {"cv": None, "cover_letter": None},
        "message": "What matters?",
    }


def test_workspace_request_requires_operation_id() -> None:
    payload = workspace_payload()
    with pytest.raises(ValidationError, match="operationId"):
        UserMessageWorkspaceRequest.model_validate(payload)

    operation_id = uuid4()
    request = UserMessageWorkspaceRequest.model_validate(
        {**payload, "operationId": str(operation_id)}
    )
    assert request.operation_id == operation_id


def test_delta_event_encodes_one_utf8_ndjson_line() -> None:
    operation_id = uuid4()
    event = WorkspaceDeltaEvent(
        operation_id=operation_id,
        sequence=2,
        text="这个岗",
    )
    encoded = encode_stream_event(event)
    assert encoded.endswith(b"\n")
    assert json.loads(encoded) == {
        "type": "delta",
        "operation_id": str(operation_id),
        "sequence": 2,
        "text": "这个岗",
    }
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd gateway
uv run pytest tests/test_task_workspace_stream_schema.py tests/test_task_protocol.py tests/test_task_workspace_schema.py -q
```

Expected: collection fails because `app.modules.task.stream_schema` does not exist, and existing
protocol assertions still observe version `2`.

- [ ] **Step 3: Implement the strict event union and request field**

Create event models with `ConfigDict(extra="forbid")`, `sequence: int = Field(ge=0)`, non-empty
delta text, and the exact discriminator values:

```python
class WorkspaceStreamStage(StrEnum):
    """Stable progress stages exposed by a Workspace event stream."""

    ROUTING = "routing"
    GENERATING_REPLY = "generating_reply"
    GENERATING_ARTIFACT = "generating_artifact"
    FINALIZING = "finalizing"


class WorkspaceDeltaEvent(WorkspaceStreamEventBase):
    """One non-empty provider text fragment for an ordinary reply."""

    type: Literal["delta"] = "delta"
    text: str = Field(min_length=1, max_length=DOCUMENT_TEXT_MAX_CHARS)


WorkspaceStreamEvent = Annotated[
    WorkspaceStartedEvent
    | WorkspaceStatusEvent
    | WorkspaceDeltaEvent
    | WorkspaceCompletedEvent
    | WorkspaceFailedEvent,
    Field(discriminator="type"),
]


def encode_stream_event(event: WorkspaceStreamEvent) -> bytes:
    """Serialize exactly one UTF-8 NDJSON event line."""

    return (event.model_dump_json() + "\n").encode("utf-8")
```

Add this exact request field and raise the wire constant:

```python
operation_id: UUID = Field(alias="operationId")
CURRENT_EXTENSION_PROTOCOL_VERSION = 3
```

Add one stable UUID `operationId` to every existing Gateway Workspace request fixture listed in
this task. Tests that intentionally exercise an invalid or absent protocol Header still send a
valid body so protocol middleware remains their only rejection boundary.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command.

Expected: all selected tests pass; protocol test bodies and headers require version `3`.

- [ ] **Step 5: Commit Task 1**

```bash
git add gateway/app/modules/task/schema.py gateway/app/modules/task/stream_schema.py gateway/app/modules/task/protocol.py gateway/tests/test_task_workspace_stream_schema.py gateway/tests/test_task_protocol.py gateway/tests/test_task_workspace_schema.py gateway/tests/test_job_match.py gateway/tests/test_job_match_orchestrator.py gateway/tests/test_job_match_router.py gateway/tests/test_job_match_specialists.py gateway/tests/test_language.py gateway/tests/test_summary_page.py gateway/tests/test_task_rate_limit.py gateway/tests/test_task_schema.py gateway/tests/test_task_workspace_api.py gateway/tests/test_task_workspace_service.py
git commit -m "feat: define workspace stream protocol"
```

---

### Task 2: Add the AsyncOpenAI Chat Completions stream boundary

**Files:**
- Create: `gateway/app/agents/stream.py`
- Create: `gateway/tests/test_agent_stream.py`
- Modify: `gateway/app/agents/base.py`

**Interfaces:**
- Produces: `ModelTextStream(model: str, chunks: AsyncIterator[str])`.
- Produces: `AgentStatus`, `AgentDelta`, `AgentCompleted`, and `AgentStreamEvent`.
- Produces: `OpenAIChatAgent.acomplete_prompt()` and `OpenAIChatAgent.open_prompt_stream()`.
- Produces: `StreamingWorkspaceAgent.stream_chat(context) -> AsyncIterator[AgentStreamEvent]`.
- Consumes: `ModelRouter.pick(prompt_length)` and `AsyncOpenAI`.

- [ ] **Step 1: Write failing async model boundary tests**

Use `asyncio.run()` rather than adding pytest-asyncio. Build a fake async Chat Completions client
whose `create(stream=True)` returns chunks containing empty and non-empty deltas:

```python
def test_open_prompt_stream_yields_non_empty_text_in_order() -> None:
    async def collect() -> tuple[str, list[str]]:
        agent = OpenAIChatAgent(
            router=ModelRouter(default=ModelTier(model="fake-model")),
            async_client=FakeAsyncClient([None, "这个岗", "位"]),
        )
        opened = await agent.open_prompt_stream(system="system", prompt="prompt")
        return opened.model, [chunk async for chunk in opened.chunks]

    assert asyncio.run(collect()) == ("fake-model", ["这个岗", "位"])


def test_async_completion_uses_non_streaming_chat_completions() -> None:
    async def execute() -> tuple[str, str]:
        client = FakeAsyncClient(["planner result"])
        agent = OpenAIChatAgent(
            router=ModelRouter(default=ModelTier(model="router-model")),
            async_client=client,
        )
        return await agent.acomplete_prompt(system="system", prompt="prompt")

    assert asyncio.run(execute()) == ("planner result", "router-model")
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
cd gateway
uv run pytest tests/test_agent_stream.py -q
```

Expected: import or attribute failures for the new stream types and async methods.

- [ ] **Step 3: Implement async clients and provider-independent events**

Add an optional injected async client without changing existing synchronous Quick Insight tests.
Cache production clients by `(tier.url, tier.key)` and expose a typed opened stream:

```python
@dataclass(frozen=True)
class ModelTextStream:
    """Selected model and one provider-independent asynchronous text stream."""

    model: str
    chunks: AsyncIterator[str]


async def _text_chunks(stream: AsyncIterator[ChatCompletionChunk]) -> AsyncIterator[str]:
    """Yield only non-empty text deltas from Chat Completions chunks."""

    async for chunk in stream:
        text = chunk.choices[0].delta.content if chunk.choices else None
        if text:
            yield text
```

`open_prompt_stream()` must call `chat.completions.create()` with `stream=True`; the file must not
reference `responses.create`. `acomplete_prompt()` calls the same async client with `stream=False`.

- [ ] **Step 4: Run model boundary and existing base tests**

```bash
cd gateway
uv run pytest tests/test_agent_stream.py tests/test_summary_page.py tests/test_job_match.py -q
```

Expected: all selected tests pass and existing synchronous Quick Insight behavior remains intact.

- [ ] **Step 5: Commit Task 2**

```bash
git add gateway/app/agents/base.py gateway/app/agents/stream.py gateway/tests/test_agent_stream.py
git commit -m "feat: add async chat completion streams"
```

---

### Task 3: Add the async ChatPlanner behind an isolated contract

**Files:**
- Create: `gateway/app/agents/job_match/planner.py`
- Create: `gateway/tests/test_job_match_planner.py`

**Interfaces:**
- Consumes: async callable `AsyncCompletePrompt(system: str, prompt: str) -> Awaitable[tuple[str, str]]`.
- Produces: `OutputMode.REPLY`, `OutputMode.ARTIFACT`, `ChatPlan`, `ChatPlanner.plan(context)`.
- Produces: `SpecialistId` from the new planner module.

- [ ] **Step 1: Write failing async planning tests**

Port the current priority and one-repair tests to an async injected completion and add output-mode
matrix cases:

```python
@pytest.mark.parametrize(
    ("specialist", "output_mode"),
    [
        (SpecialistId.JOB_ANALYSIS, OutputMode.REPLY),
        (SpecialistId.RESUME, OutputMode.REPLY),
        (SpecialistId.RESUME, OutputMode.ARTIFACT),
        (SpecialistId.COVER_LETTER, OutputMode.REPLY),
        (SpecialistId.COVER_LETTER, OutputMode.ARTIFACT),
        (SpecialistId.GENERAL_QA, OutputMode.REPLY),
    ],
)
def test_planner_accepts_legal_plans(
    specialist: SpecialistId,
    output_mode: OutputMode,
) -> None:
    raw = json.dumps({"specialist": specialist, "output_mode": output_mode})
    planner = ChatPlanner(complete_prompt=async_completion([raw]))
    decision = asyncio.run(planner.plan(context()))
    assert decision == ChatPlan(specialist=specialist, output_mode=output_mode)


def test_planner_rejects_artifact_for_analysis_after_one_repair() -> None:
    invalid = '{"specialist":"job_analysis","output_mode":"artifact"}'
    planner = ChatPlanner(complete_prompt=async_completion([invalid, invalid]))
    with pytest.raises(ChatPlanningError, match="invalid structured chat plan"):
        asyncio.run(planner.plan(context()))
```

- [ ] **Step 2: Run planner tests and verify RED**

```bash
cd gateway
uv run pytest tests/test_job_match_planner.py -q
```

Expected: import failure because `planner.py` does not exist.

- [ ] **Step 3: Implement strict planning and one repair attempt**

Use a frozen, extra-forbid Pydantic model and validate illegal specialist/mode combinations in a
model validator:

```python
class OutputMode(StrEnum):
    """Whether one Specialist returns a chat reply or a complete Artifact draft."""

    REPLY = "reply"
    ARTIFACT = "artifact"


class ChatPlan(BaseModel):
    """Validated Specialist and output-mode decision for one Workspace turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    specialist: SpecialistId
    output_mode: OutputMode

    @model_validator(mode="after")
    def validate_matrix(self) -> "ChatPlan":
        """Forbid Artifact output from reply-only Specialists."""

        if self.output_mode is OutputMode.ARTIFACT and self.specialist in {
            SpecialistId.JOB_ANALYSIS,
            SpecialistId.GENERAL_QA,
        }:
            raise ValueError("selected Specialist cannot create an Artifact")
        return self
```

The planner prompt must retain the existing priority and explicitly decide both fields. Repair is
attempted exactly once, then raises `ChatPlanningError`.

- [ ] **Step 4: Run the isolated planner contract**

```bash
cd gateway
uv run pytest tests/test_job_match_planner.py -q
```

Expected: all planner tests pass while the current Agent still uses `IntentRouter` until Task 4.

- [ ] **Step 5: Commit Task 3**

```bash
git add gateway/app/agents/job_match/planner.py gateway/tests/test_job_match_planner.py
git commit -m "refactor: plan job workspace output modes"
```

---

### Task 4: Stream Job Match and Summary Page Agent results

**Files:**
- Modify: `gateway/app/agents/job_match/specialists/base.py`
- Modify: `gateway/app/agents/job_match/specialists/analysis.py`
- Modify: `gateway/app/agents/job_match/specialists/resume.py`
- Modify: `gateway/app/agents/job_match/specialists/cover_letter.py`
- Modify: `gateway/app/agents/job_match/specialists/general_qa.py`
- Modify: `gateway/app/agents/job_match/agent.py`
- Modify: `gateway/app/agents/job_match/__init__.py`
- Modify: `gateway/app/agents/summary_page.py`
- Modify: `gateway/app/agents/base.py`
- Delete: `gateway/app/agents/job_match/router.py`
- Delete: `gateway/tests/test_job_match_router.py`
- Modify: `gateway/tests/test_job_match_specialists.py`
- Modify: `gateway/tests/test_job_match_orchestrator.py`
- Modify: `gateway/tests/test_summary_page.py`

**Interfaces:**
- Consumes: `ChatPlan`, `OutputMode`, `ModelTextStream`, and Agent stream event types from Tasks 2-3.
- Produces: every registered Agent implements `stream_chat(context) -> AsyncIterator[AgentStreamEvent]`.
- Produces: one terminal `AgentCompleted(execution=AgentExecution[ChatResult])` per successful stream.

- [ ] **Step 1: Write failing Strategy and orchestration stream tests**

Test ordinary replies expose deltas, Artifact plans hide chunks, deterministic Quick Actions skip
planning, and Summary Page is reply-only:

```python
def test_resume_reply_streams_markdown_deltas() -> None:
    events = asyncio.run(
        collect_events(
            job_agent(
                plan=ChatPlan(
                    specialist=SpecialistId.RESUME,
                    output_mode=OutputMode.REPLY,
                ),
                chunks=["## Advice", "\n\nHighlight Go."],
            ).stream_chat(workspace_context())
        )
    )
    assert [event.text for event in events if isinstance(event, AgentDelta)] == [
        "## Advice",
        "\n\nHighlight Go.",
    ]
    assert isinstance(events[-1], AgentCompleted)
    assert events[-1].execution.content.markdown == "## Advice\n\nHighlight Go."


def test_cover_letter_artifact_exposes_status_but_no_delta() -> None:
    events = asyncio.run(
        collect_events(
            job_agent(
                plan=ChatPlan(
                    specialist=SpecialistId.COVER_LETTER,
                    output_mode=OutputMode.ARTIFACT,
                ),
                chunks=["# Cover Letter", "\n\nDear Hiring Manager"],
            ).stream_chat(workspace_context())
        )
    )
    assert not any(isinstance(event, AgentDelta) for event in events)
    completed = cast(AgentCompleted, events[-1]).execution.content
    assert completed.type in {"create_artifact", "update_artifact"}
    assert completed.draft == "# Cover Letter\n\nDear Hiring Manager"
```

- [ ] **Step 2: Run Agent tests and verify RED**

```bash
cd gateway
uv run pytest tests/test_job_match_specialists.py tests/test_job_match_orchestrator.py tests/test_summary_page.py -q
```

Expected: failures because Agents still expose synchronous `handle_chat()` and JSON Specialist
results.

- [ ] **Step 3: Implement raw-Markdown streaming Strategies and Facade**

Replace the structured-result parser with a Template Method that opens raw Markdown streams for a
validated output mode:

```python
class StreamingJobMatchSpecialist(ABC):
    """Template Method for one mode-constrained raw Markdown Specialist stream."""

    allowed_modes: ClassVar[frozenset[OutputMode]]

    async def open_stream(
        self,
        context: JobChatContext,
        output_mode: OutputMode,
    ) -> SpecialistTextStream:
        """Validate mode, build prompts, and open one Chat Completions stream."""

        if output_mode not in self.allowed_modes:
            raise ValueError("Specialist output mode is not allowed")
        prompt = self.build_prompt(context, output_mode)
        system = self.build_system_prompt(context.request.lang, output_mode)
        opened = await self._open_prompt_stream(system=system, prompt=prompt)
        return SpecialistTextStream(
            prompt=prompt,
            model=opened.model,
            chunks=opened.chunks,
        )
```

`JobMatchAgent.stream_chat()` must emit routing/generation/finalizing statuses, expose chunks only
for reply plans, enforce non-empty and 100,000-character limits, and create deterministic Artifact
titles/completion notes. `SummaryPageAgent.stream_chat()` uses the same raw reply pattern without a
planner. Switch Agent imports and constructor injection from `IntentRouter` to `ChatPlanner`, then
delete the superseded Router module and its tests in the same green commit.

- [ ] **Step 4: Run all Agent tests and verify GREEN**

```bash
cd gateway
uv run pytest tests/test_agent_stream.py tests/test_job_match.py tests/test_job_match_planner.py tests/test_job_match_specialists.py tests/test_job_match_orchestrator.py tests/test_summary_page.py -q
```

Expected: all selected tests pass; no Job Match prompt requires a JSON reply/artifact envelope.

- [ ] **Step 5: Commit Task 4**

```bash
git rm gateway/app/agents/job_match/router.py gateway/tests/test_job_match_router.py
git add gateway/app/agents/base.py gateway/app/agents/job_match/__init__.py gateway/app/agents/job_match/agent.py gateway/app/agents/job_match/planner.py gateway/app/agents/job_match/specialists/base.py gateway/app/agents/job_match/specialists/analysis.py gateway/app/agents/job_match/specialists/resume.py gateway/app/agents/job_match/specialists/cover_letter.py gateway/app/agents/job_match/specialists/general_qa.py gateway/app/agents/summary_page.py gateway/tests/test_job_match.py gateway/tests/test_job_match_planner.py gateway/tests/test_job_match_specialists.py gateway/tests/test_job_match_orchestrator.py gateway/tests/test_summary_page.py
git commit -m "feat: stream workspace agent markdown"
```

---

### Task 5: Stream TaskService events through the Workspace API

**Files:**
- Modify: `gateway/app/modules/task/service.py`
- Modify: `gateway/app/modules/task/api.py`
- Modify: `gateway/tests/test_task_workspace_service.py`
- Modify: `gateway/tests/test_task_workspace_api.py`
- Modify: `gateway/tests/test_task_rate_limit.py`
- Modify: `gateway/tests/test_tasks_auth.py`

**Interfaces:**
- Consumes: `StreamingWorkspaceAgent`, `AgentStreamEvent`, and Task wire event models.
- Produces: `PreparedWorkspaceStream` and `TaskService.stream_workspace(prepared)`.
- Produces: `POST /tasks/workspace` as `application/x-ndjson` with anti-buffering headers.

- [ ] **Step 1: Write failing service and API stream tests**

Create a fake Agent async generator and collect events with `asyncio.run()`. Assert final reduction
is unchanged and failure never emits completed:

```python
def test_workspace_reply_stream_reduces_only_at_completed() -> None:
    service, repository = service_with_agent(
        StreamingReplyAgent(chunks=["这个岗", "位很匹配"])
    )
    prepared = service.prepare_workspace_stream(request(), user_id=None)
    events = asyncio.run(collect_events(service.stream_workspace(prepared)))

    assert [event.type for event in events] == [
        "started",
        "status",
        "delta",
        "delta",
        "status",
        "completed",
    ]
    assert events[-1].response.histories[-1].content == "这个岗位很匹配"
    assert repository.records[-1].status == "completed"


def test_workspace_api_returns_ndjson_and_no_buffer_headers(monkeypatch) -> None:
    wire_streaming_service(monkeypatch)
    with TestClient(main.app).stream(
        "POST",
        "/tasks/workspace",
        headers={"X-Agent-Bridge-Protocol-Version": "3"},
        json=payload(operationId=str(uuid4())),
    ) as response:
        lines = [json.loads(line) for line in response.iter_lines()]

    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"
    assert lines[0]["type"] == "started"
    assert lines[-1]["type"] == "completed"
```

- [ ] **Step 2: Run service/API tests and verify RED**

```bash
cd gateway
uv run pytest tests/test_task_workspace_service.py tests/test_task_workspace_api.py tests/test_task_rate_limit.py tests/test_tasks_auth.py -q
```

Expected: failures because `prepare_workspace_stream()` and `stream_workspace()` do not exist and
the route still returns JSON.

- [ ] **Step 3: Implement prepared execution, async mapping, and StreamingResponse**

Add a request-scoped immutable preparation value. Preparation performs every check that must still
produce an ordinary HTTP error:

```python
@dataclass(frozen=True)
class PreparedWorkspaceStream:
    """Validated dependencies for one stateless Workspace event stream."""

    request: WorkspaceRequest
    resource_url: str
    agent_name: AgentName
    agent: StreamingWorkspaceAgent
    context: WorkspaceAgentContext
    user_id: str | None
    started_at: datetime
```

`stream_workspace()` assigns sequence numbers, maps internal events, accumulates timing, calls the
existing `_validated_workspace_execution()`, `_allocate_workspace_transition_identity()`, and
`_reduce_workspace_state()` only after `AgentCompleted`, persists one terminal record, and emits one
terminal wire event.

The API remains thin:

```python
@router.post("/tasks/workspace", response_class=StreamingResponse)
async def create_workspace_task(
    task: WorkspaceRequest,
    request: Request,
) -> StreamingResponse:
    """Stream one stateless Workspace transition as NDJSON."""

    service = get_task_service(request)
    prepared = service.prepare_workspace_stream(task, user_id=_user_id(request))

    async def body() -> AsyncIterator[bytes]:
        """Encode service events and stop work after client disconnect."""

        events = service.stream_workspace(prepared)
        try:
            async for event in events:
                if await request.is_disconnected():
                    break
                yield encode_stream_event(event)
        finally:
            await events.aclose()

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Map preparation failures through the existing HTTP error function. Once `started` is emitted,
convert all ordinary exceptions to one bounded `failed` event.

- [ ] **Step 4: Run Gateway Workspace and protocol tests**

```bash
cd gateway
uv run pytest tests/test_task_workspace_service.py tests/test_task_workspace_api.py tests/test_task_protocol.py tests/test_task_rate_limit.py tests/test_tasks_auth.py -q
```

Expected: all selected tests pass; successful Workspace responses are NDJSON only.

- [ ] **Step 5: Commit Task 5**

```bash
git add gateway/app/modules/task/api.py gateway/app/modules/task/service.py gateway/tests/test_task_workspace_service.py gateway/tests/test_task_workspace_api.py gateway/tests/test_task_protocol.py gateway/tests/test_task_rate_limit.py gateway/tests/test_tasks_auth.py
git commit -m "feat: stream workspace task events"
```

---

### Task 6: Parse protocol-v3 NDJSON in the Extension

**Files:**
- Create: `extension/workspace-stream.js`
- Create: `extension/workspace-stream.test.js`
- Modify: `extension/config.js`
- Modify: `extension/config.test.js`
- Modify: `extension/auth.js`
- Modify: `extension/auth.test.js`
- Modify: `extension/workspace-controller.js`
- Modify: `extension/workspace-controller.test.js`

**Interfaces:**
- Produces: `readWorkspaceEventStream(response) -> AsyncGenerator<WorkspaceStreamEvent>`.
- Produces: `validateWorkspaceStreamEvent(value)` and `buildWorkspaceHeaders(token)`.
- Consumes: existing protocol update errors and final `applyWorkspaceResponse()` validation.

- [ ] **Step 1: Write failing parser and request tests**

Build `ReadableStream` responses whose UTF-8 bytes split within both JSON lines and Chinese
characters:

```javascript
test("NDJSON parser preserves a Chinese code point split across byte chunks", async () => {
  const encoded = new TextEncoder().encode(
    '{"type":"delta","operation_id":"00000000-0000-0000-0000-000000000001","sequence":1,"text":"岗"}\n'
  );
  const split = encoded.indexOf(0xe5) + 1;
  const response = streamResponse([encoded.slice(0, split), encoded.slice(split)]);
  const events = [];
  for await (const event of readWorkspaceEventStream(response)) events.push(event);
  assert.equal(events[0].text, "岗");
});


test("workspace request requires one operationId and NDJSON Accept header", () => {
  const operationId = "00000000-0000-0000-0000-000000000001";
  const body = buildUserMessageWorkspaceBody(pageContext(), {
    resourceUrl: "https://example.com/article",
    actionId: "ask_more",
    state: { histories: [], artifacts: { cv: null, cover_letter: null } },
    message: "What matters?",
    lang: "en",
    operationId,
  });
  assert.equal(body.operationId, operationId);
  assert.equal(buildWorkspaceHeaders("token").Accept, "application/x-ndjson");
  assert.equal(EXTENSION_PROTOCOL_VERSION, 3);
});
```

- [ ] **Step 2: Run focused Extension tests and verify RED**

```bash
cd extension
node --test workspace-stream.test.js auth.test.js config.test.js workspace-controller.test.js
```

Expected: module-not-found and protocol-version assertion failures.

- [ ] **Step 3: Implement strict incremental parsing**

Use one streaming `TextDecoder`, retain the incomplete tail, and validate terminal state:

```javascript
export async function* readWorkspaceEventStream(response) {
  await assertGatewayStreamResponse(response);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminalCount = 0;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : lines.pop();
    for (const line of lines) {
      if (!line) continue;
      const event = validateWorkspaceStreamEvent(JSON.parse(line));
      if (event.type === "completed" || event.type === "failed") terminalCount += 1;
      yield event;
    }
    if (done) break;
  }

  if (buffer.trim()) throw new TypeError("Workspace stream ended with invalid NDJSON");
  if (terminalCount !== 1) throw new TypeError("Workspace stream requires one terminal event");
}
```

Validate exact event keys, UUID, sequence, stages, status-specific Artifact fields, and completed
protocol version. Refactor the existing protocol-header-first logic into a reusable exported helper
so 401 cannot clear auth before version validation.

- [ ] **Step 4: Run parser and protocol consumer tests**

Run the Step 2 command.

Expected: all selected tests pass, including multi-line chunks, split lines, invalid trailing JSON,
duplicate terminal events, and protocol mismatch.

- [ ] **Step 5: Commit Task 6**

```bash
git add extension/workspace-stream.js extension/workspace-stream.test.js extension/config.js extension/config.test.js extension/auth.js extension/auth.test.js extension/workspace-controller.js extension/workspace-controller.test.js
git commit -m "feat: parse workspace ndjson streams"
```

---

### Task 7: Coordinate streams in Extension Background

**Files:**
- Modify: `extension/workspace-operation.js`
- Modify: `extension/workspace-operation.test.js`
- Modify: `extension/background.js`
- Modify: `extension/background.test.js`
- Modify: `extension/workspace-controller.js`
- Modify: `extension/workspace-controller.test.js`

**Interfaces:**
- Consumes: `readWorkspaceEventStream()`, request `operationId`, existing keyed queue, and `applyWorkspaceResponse()`.
- Produces: `AGENT_BRIDGE_WORKSPACE_STREAM` cumulative runtime events.
- Produces: `WORKSPACE_GET` response field `pendingStream`.
- Produces: abort on tab removal, owner change, timeout, and final terminal event.

- [ ] **Step 1: Write failing stream coordinator tests**

Extend the pure operation runner with an event callback and ensure only terminal complete state is
applied:

```javascript
test("stream operation broadcasts cumulative snapshots and applies only completed", async () => {
  const snapshots = [];
  const applied = [];
  const result = await runWorkspaceOperation(operation(), {
    queue: immediateQueue(),
    key: "workspace-a",
    loadLatest: async () => latestState(),
    collectPageContext: async () => pageContext(),
    buildRequest: () => requestBody(),
    executeRequest: async function* () {
      yield started(0);
      yield delta(1, "这个岗");
      yield delta(2, "位");
      yield completed(3, workspaceResponse());
    },
    onEvent: (event, snapshot) => snapshots.push({ event, snapshot }),
    applyResponse: async (_latest, response) => {
      applied.push(response);
      return response;
    },
  });

  assert.deepEqual(snapshots.map((item) => item.snapshot.markdown), ["", "这个岗", "这个岗位", "这个岗位"]);
  assert.equal(applied.length, 1);
  assert.equal(result, applied[0]);
});
```

Add Background source/behavior tests for active snapshots returned by `WORKSPACE_GET`, stale
sequence rejection, failed streams, and abort on `tabs.onRemoved`.

- [ ] **Step 2: Run coordinator tests and verify RED**

```bash
cd extension
node --test workspace-operation.test.js background.test.js workspace-controller.test.js
```

Expected: failures because the runner expects one complete response and Background still calls
`readGatewayResponse()`.

- [ ] **Step 3: Implement active stream records and cumulative notifications**

Give every request operation an explicit ID. Side Panel supplies it for user messages; Background
uses `crypto.randomUUID()` for Quick Actions. Refactor execution so the fetch response is consumed
as events:

```javascript
const activeWorkspaceStreams = new Map();

function acceptStreamEvent(active, event) {
  if (event.operation_id !== active.operationId || event.sequence <= active.sequence) return false;
  active.sequence = event.sequence;
  active.stage = event.stage || active.stage;
  if (event.type === "delta") active.markdown += event.text;
  return true;
}

function streamSnapshot(active) {
  return {
    operationId: active.operationId,
    tabId: active.tabId,
    resourceUrl: active.resourceUrl,
    sequence: active.sequence,
    stage: active.stage,
    markdown: active.markdown,
    submittedMessage: active.submittedMessage,
    createdAt: active.createdAt,
  };
}
```

Broadcast cumulative snapshots through `AGENT_BRIDGE_WORKSPACE_STREAM`. Validate the terminal
`completed.response`, write it once, notify Workspace updated, and clear transient state. Convert
`failed` or an unterminated stream to the existing recoverable error path without applying state.

- [ ] **Step 4: Run coordinator and full Background tests**

```bash
cd extension
node --test workspace-stream.test.js workspace-operation.test.js background.test.js workspace-controller.test.js
```

Expected: all selected tests pass; the source has one Workspace fetch pipeline and no Workspace
call to `readGatewayResponse()`.

- [ ] **Step 5: Commit Task 7**

```bash
git add extension/workspace-operation.js extension/workspace-operation.test.js extension/background.js extension/background.test.js extension/workspace-controller.js extension/workspace-controller.test.js
git commit -m "feat: coordinate workspace stream state"
```

---

### Task 8: Render optimistic and streamed Side Panel turns

**Files:**
- Modify: `extension/sidepanel.js`
- Modify: `extension/sidepanel.css`
- Modify: `extension/sidepanel.test.js`

**Interfaces:**
- Consumes: `AGENT_BRIDGE_WORKSPACE_STREAM` cumulative snapshots and terminal Workspace reloads.
- Produces: non-persistent `model.pendingTurn` and throttled Assistant Markdown rendering.
- Preserves: stable form IDs, local timestamps, Marked + DOMPurify, and canonical state rendering.

- [ ] **Step 1: Write failing optimistic UI tests**

Test immediate User rendering, input clearing, delta snapshots, failure restoration, and terminal
replacement:

```javascript
test("submit immediately renders a transient user turn and clears the composer", async () => {
  const setup = sidePanelSetup({ histories: [] });
  setup.elements.messageInput.value = "这个岗位最看重什么？";
  const pending = deferred();

  const submit = submitMessage(setup.elements, setup.model, {
    randomUUID: () => "00000000-0000-0000-0000-000000000001",
    sendRuntime: () => pending.promise,
  });

  assert.equal(setup.elements.messageInput.value, "");
  assert.equal(setup.model.pendingTurn.userText, "这个岗位最看重什么？");
  assert.match(setup.elements.timeline.textContent, /这个岗位最看重什么/);
  pending.resolve({ ok: true, state: completedState(), lang: "zh" });
  await submit;
});


test("failed stream restores text without changing canonical histories", async () => {
  const setup = sidePanelSetup({ histories: [history("canonical")] });
  startPendingTurn(setup, "retry me");
  dispatchWorkspaceStream(setup, failedSnapshot());
  assert.equal(setup.elements.messageInput.value, "retry me");
  assert.deepEqual(setup.model.state.histories.map((item) => item.content), ["canonical"]);
  assert.match(setup.elements.timeline.textContent, /failed|失败/i);
});
```

- [ ] **Step 2: Run Side Panel tests and verify RED**

```bash
cd extension
node --test sidepanel.test.js
```

Expected: failures because `pendingTurn` and stream lifecycle events are not rendered.

- [ ] **Step 3: Implement transient turn rendering and 50 ms throttling**

Generate the operation ID before `WORKSPACE_SEND`, keep the original message in `pendingTurn`,
render it after canonical histories, and update only when tab/resource/operation/sequence match.

Use a single scheduled render rather than parsing Markdown on every token:

```javascript
function scheduleStreamRender(model, renderNow, dependencies = {}) {
  if (model.streamRenderTimer != null) return;
  const schedule = dependencies.setTimeout || globalThis.setTimeout;
  model.streamRenderTimer = schedule(() => {
    model.streamRenderTimer = null;
    renderNow();
  }, 50);
}
```

On completed response, clear the transient turn and render canonical state. On failed/interrupted
state, retain a failed Assistant row and restore the submitted message. Add restrained pending and
failure styles that reuse the current Quiet Precision tokens and respect reduced motion.

- [ ] **Step 4: Run Side Panel and full Extension tests**

```bash
cd extension
npm test
```

Expected: every Extension test passes, including existing tab-switch, owner-change, message-limit,
Markdown, Attachment, and responsive CSS contracts.

- [ ] **Step 5: Commit Task 8**

```bash
git add extension/sidepanel.js extension/sidepanel.css extension/sidepanel.test.js
git commit -m "feat: render streamed workspace turns"
```

---

### Task 9: Disable proxy buffering, update docs, package, and verify end-to-end

**Files:**
- Modify: `deploy/nginx.conf`
- Create: `gateway/tests/test_workspace_stream_deployment.py`
- Modify: `gateway/app/modules/task/README.md`
- Modify: `gateway/app/agents/job_match/README.md`
- Modify: `extension/README.md`
- Modify: `deploy/DEPLOY.docker.zh-CN.md`
- Modify: `extension/scripts/verify-package.mjs`

**Interfaces:**
- Consumes: all protocol-v3 runtime modules and current Docker Nginx boundary.
- Produces: unbuffered `/api/tasks/workspace`, packaged stream parser, and user-facing documentation.

- [ ] **Step 1: Write failing deployment and package assertions**

Add a static Gateway test that reads `deploy/nginx.conf` and proves the Workspace path is
unbuffered, plus a package test that requires `workspace-stream.js`:

```python
def test_workspace_proxy_disables_buffering() -> None:
    config = (REPO_ROOT / "deploy" / "nginx.conf").read_text()
    match = re.search(
        r"location\s*=\s*/api/tasks/workspace\s*\{(?P<body>.*?)\n\s*\}",
        config,
        re.DOTALL,
    )
    assert match is not None
    workspace_location = match.group("body")
    assert "proxy_buffering off;" in workspace_location
    assert "proxy_cache off;" in workspace_location
```

```javascript
test("production package contains Workspace streaming runtime", () => {
  const entries = zipEntries(packagePath);
  assert.ok(entries.includes("workspace-stream.js"));
});
```

- [ ] **Step 2: Run deployment/package tests and verify RED**

```bash
cd gateway
uv run pytest tests/test_workspace_stream_deployment.py -q
cd ../extension
npm run test:package
```

Expected: Nginx assertion fails and the package does not contain `workspace-stream.js`.

- [ ] **Step 3: Add the unbuffered proxy boundary and update documentation**

Add a Workspace-specific location before the general `/api/` location, preserving all proxy
headers:

```nginx
location = /api/tasks/workspace {
    proxy_pass http://gateway:17321/tasks/workspace;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Add `workspace-stream.js` to the explicit package allowlist. Update each README with the
Chat-Completions-only pipeline, optimistic/transient distinction, NDJSON terminal state, protocol
v3 requirement, Artifact status-only rule, and Nginx buffering requirement.

- [ ] **Step 4: Run complete verification**

```bash
cd gateway
uv run pytest
uv run python -c "import app.main; print('main import ok')"
cd ../extension
npm test
npm run test:package
npm run package
cd ..
git diff --check
```

Expected:

- Gateway suite: zero failures.
- Import check prints `main import ok`.
- Extension suite: zero failures.
- Package verification: zero failures and `workspace-stream.js` is present.
- Production ZIP builds successfully.
- `git diff --check` prints nothing.

- [ ] **Step 5: Perform one real local acceptance run**

Reload the unpacked Extension, open a LinkedIn or Indeed job, and verify:

1. User Message appears before the Gateway completes.
2. Analyze/Ask More visibly updates Markdown before `completed`.
3. Resume/Cover Letter displays generation status but no draft text.
4. A successful terminal event survives Side Panel reload as canonical history.
5. An induced provider failure restores the composer and adds no history.

Capture Gateway logs without page body, prompt, model response, bearer token, or provider key.

- [ ] **Step 6: Commit Task 9**

```bash
git add deploy/nginx.conf deploy/DEPLOY.docker.zh-CN.md gateway/tests/test_workspace_stream_deployment.py gateway/app/modules/task/README.md gateway/app/agents/job_match/README.md extension/README.md extension/package.sh extension/scripts/verify-package.mjs
git commit -m "feat: ship workspace streaming boundary"
```

---

## Final review checklist

- [ ] `POST /tasks/workspace` has no successful JSON-only path under protocol v3.
- [ ] Protocol v2 always receives `426` before auth/body parsing.
- [ ] Quick Insight remains ordinary JSON.
- [ ] No model code references `responses.create`.
- [ ] Reply deltas are transient; Artifact drafts are never emitted as deltas.
- [ ] Only `completed.response` reaches `applyWorkspaceResponse()` and Chrome local storage.
- [ ] Failure and disconnect cannot append histories or update Artifacts.
- [ ] Side Panel never renders stale tab/resource/operation sequences.
- [ ] Nginx and Gateway both disable response buffering.
- [ ] README files describe current behavior rather than implementation aspirations.
