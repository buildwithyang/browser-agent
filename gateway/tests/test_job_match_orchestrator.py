"""Streaming Facade/Mediator tests for Job Match Workspace orchestration."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

import app.agents.job_match.agent as job_match_agent_module
from app.agents.base import WorkspaceAgentContext
from app.agents.job_match import JobMatchAgent
from app.agents.job_match.context import JobChatContext
from app.agents.job_match.planner import ChatPlan, OutputMode, SpecialistId
from app.agents.stream import AgentCompleted, AgentDelta, AgentStatus, AgentStreamEvent
from app.modules.task.schema import (
    Artifact,
    ArtifactType,
    Artifacts,
    Attachment,
    CreateArtifactResult,
    DOCUMENT_TEXT_MAX_CHARS,
    HistoryMessage,
    ReplyResult,
    UpdateArtifactResult,
    WorkspaceRequest,
)


LONG_JD = (
    "Senior Backend Engineer responsible for distributed Go services, APIs, "
    "Kubernetes, observability, reliability, and cross-team architecture. "
) * 12


class SpyPlanner:
    """Record planning calls while returning one deterministic plan."""

    def __init__(self, plan: ChatPlan) -> None:
        """Configure the fixed plan selected for each invocation."""

        self.result = plan
        self.calls: list[JobChatContext] = []

    async def plan(self, context: JobChatContext) -> ChatPlan:
        """Record one immutable context and return the configured plan."""

        self.calls.append(context)
        return self.result


class TrackingChunkStream:
    """Track deterministic cleanup of a Specialist text iterator."""

    def __init__(self, chunks: list[str]) -> None:
        """Store ordered chunks and initialize stream lifecycle state."""

        self._chunks = iter(chunks)
        self.closed = False

    def __aiter__(self) -> "TrackingChunkStream":
        """Return this iterator for asynchronous consumption."""

        return self

    async def __anext__(self) -> str:
        """Return the next configured chunk or terminate the stream."""

        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None

    async def aclose(self) -> None:
        """Record immediate cleanup requested by the Agent."""

        self.closed = True


class PlainChunkStream:
    """Provide a valid async iterator without an optional cleanup method."""

    def __init__(self, chunks: list[str]) -> None:
        """Store ordered chunks for deterministic asynchronous consumption."""

        self._chunks = iter(chunks)

    def __aiter__(self) -> "PlainChunkStream":
        """Return this iterator for asynchronous consumption."""

        return self

    async def __anext__(self) -> str:
        """Return the next configured chunk or terminate the stream."""

        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None


class SpySpecialist:
    """Record Strategy calls while returning a prepared Markdown stream."""

    def __init__(
        self,
        chunks: list[str],
        *,
        name: str,
        model: str | None = None,
        closeable: bool = True,
    ) -> None:
        """Configure raw chunks and observable execution metadata."""

        self.chunks = chunks
        self.name = name
        self.model = model or f"{name}-model"
        self.closeable = closeable
        self.calls: list[tuple[JobChatContext, OutputMode]] = []
        self.streams: list[TrackingChunkStream | PlainChunkStream] = []

    async def open_stream(
        self,
        context: JobChatContext,
        output_mode: OutputMode,
    ) -> object:
        """Record one request and expose the configured raw Markdown stream."""

        self.calls.append((context, output_mode))

        stream = (
            TrackingChunkStream(self.chunks)
            if self.closeable
            else PlainChunkStream(self.chunks)
        )
        self.streams.append(stream)

        return SimpleNamespace(
            prompt=f"{self.name}-prompt",
            model=self.model,
            chunks=stream,
        )


class LoopBoundProviderStream:
    """Yield provider chunks while tracking explicit stream closure."""

    def __init__(self, text: str) -> None:
        """Configure one provider text chunk."""

        self._text = text
        self._done = False
        self.closed = False

    def __aiter__(self) -> "LoopBoundProviderStream":
        """Return this provider iterator."""

        return self

    async def __anext__(self) -> SimpleNamespace:
        """Yield one OpenAI-compatible chunk then terminate."""

        if self._done:
            raise StopAsyncIteration
        self._done = True
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=self._text))]
        )

    async def aclose(self) -> None:
        """Record explicit provider-stream cleanup."""

        self.closed = True


class LoopBoundAsyncClient:
    """Reject use outside the event loop that first opened this client."""

    def __init__(self) -> None:
        """Initialize an unbound realistic AsyncOpenAI lifecycle double."""

        self._loop: asyncio.AbstractEventLoop | None = None
        self.closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: object) -> object:
        """Bind on first use and fail if a later request reuses another loop."""

        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("Event loop is closed")
        if self.closed:
            raise RuntimeError("client is closed")
        if kwargs.get("stream") is True:
            return LoopBoundProviderStream("## Answer")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"specialist":"general_qa","output_mode":"reply"}'
                    )
                )
            ]
        )

    async def close(self) -> None:
        """Require internally-owned client cleanup on its bound loop."""

        assert asyncio.get_running_loop() is self._loop
        self.closed = True


def _artifact_state(
    *existing_types: ArtifactType,
) -> tuple[Artifacts, list[HistoryMessage]]:
    """Build valid current Artifact snapshots and latest message Attachments."""

    artifacts: dict[ArtifactType, Artifact] = {}
    histories: list[HistoryMessage] = []
    for artifact_type in existing_types:
        artifact_id = uuid4()
        title = "Existing CV" if artifact_type is ArtifactType.CV else "Existing Letter"
        draft = "# Existing CV" if artifact_type is ArtifactType.CV else "# Existing Letter"
        attachment = Attachment(
            artifact_id=artifact_id,
            version=1,
            type=artifact_type,
            title=title,
            content="https://example.com/cv.pdf" if artifact_type is ArtifactType.CV else draft,
        )
        artifacts[artifact_type] = Artifact(
            id=artifact_id,
            type=artifact_type,
            version=1,
            title=title,
            draft=draft,
            attachment=attachment,
        )
        histories.append(
            HistoryMessage(
                role="user",
                content=f"Please prepare {title}.",
            )
        )
        histories.append(
            HistoryMessage(
                role="assistant",
                content=f"Prepared {title}.",
                attachments=[attachment],
            )
        )
    return (
        Artifacts(
            cv=artifacts.get(ArtifactType.CV),
            cover_letter=artifacts.get(ArtifactType.COVER_LETTER),
        ),
        histories,
    )


def _context(
    *,
    message: str = "What should I emphasize?",
    existing_types: tuple[ArtifactType, ...] = (),
    resume_text: str | None = "# Canonical Resume",
    lang: str = "en",
) -> WorkspaceAgentContext:
    """Build one valid immutable v4 Workspace Agent context."""

    artifacts, histories = _artifact_state(*existing_types)
    request = WorkspaceRequest(
        url="https://www.linkedin.com/jobs/view/123",
        resourceUrl="https://www.linkedin.com/jobs/view/123",
        operationId="00000000-0000-0000-0000-000000000001",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        pageText="Full job page.",
        lang=lang,
        histories=histories,
        artifacts=artifacts,
        message=message,
    )
    return WorkspaceAgentContext(request=request, resume_text=resume_text)


def _specialists(
    *,
    chunks: list[str],
    selected: SpecialistId,
    model: str | None = None,
    closeable: bool = True,
) -> Mapping[SpecialistId, SpySpecialist]:
    """Build a complete injectable Strategy registry with one selected output."""

    return {
        specialist_id: SpySpecialist(
            chunks if specialist_id is selected else ["unexpected"],
            name=specialist_id.value,
            model=model if specialist_id is selected else None,
            closeable=closeable if specialist_id is selected else True,
        )
        for specialist_id in SpecialistId
    }


def _job_agent(
    *,
    plan: ChatPlan,
    chunks: list[str],
    model: str | None = None,
    closeable: bool = True,
) -> tuple[JobMatchAgent, SpyPlanner, Mapping[SpecialistId, SpySpecialist]]:
    """Build one streaming Facade and its observable collaborators."""

    planner = SpyPlanner(plan)
    specialists = _specialists(
        chunks=chunks,
        selected=plan.specialist,
        model=model,
        closeable=closeable,
    )
    return (
        JobMatchAgent(planner=planner, specialists=specialists),
        planner,
        specialists,
    )


async def _collect_events(stream: AsyncIterator[AgentStreamEvent]) -> list[AgentStreamEvent]:
    """Collect one Agent stream for synchronous tests."""

    return [event async for event in stream]


def test_resume_reply_streams_markdown_deltas() -> None:
    """Expose reply chunks while accumulating the same terminal Markdown."""

    agent, planner, specialists = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.RESUME, output_mode=OutputMode.REPLY),
        chunks=["## Advice", "\n\nHighlight Go."],
    )

    events = asyncio.run(_collect_events(agent.stream_chat(_context())))

    assert [event.text for event in events if isinstance(event, AgentDelta)] == [
        "## Advice",
        "\n\nHighlight Go.",
    ]
    assert [event.stage for event in events if isinstance(event, AgentStatus)] == [
        "routing",
        "generating_reply",
        "finalizing",
    ]
    completed = cast(AgentCompleted, events[-1])
    assert completed.execution.content == ReplyResult(
        type="reply",
        markdown="## Advice\n\nHighlight Go.",
    )
    assert len(planner.calls) == 1
    assert sum(len(specialist.calls) for specialist in specialists.values()) == 1


def test_job_agent_completes_with_plain_async_iterator_without_aclose() -> None:
    """Complete normally when the declared async iterator has no cleanup hook."""

    agent, _planner, _specialists_map = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.RESUME, output_mode=OutputMode.REPLY),
        chunks=["Plain reply."],
        closeable=False,
    )

    events = asyncio.run(_collect_events(agent.stream_chat(_context())))

    assert [event.stage for event in events if isinstance(event, AgentStatus)] == [
        "routing",
        "generating_reply",
        "finalizing",
    ]
    completed = cast(AgentCompleted, events[-1])
    assert completed.execution.content == ReplyResult(
        type="reply",
        markdown="Plain reply.",
    )


def test_closing_job_agent_stream_closes_specialist_chunks() -> None:
    """Propagate consumer cancellation to the opened Specialist iterator."""

    agent, _planner, specialists = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.RESUME, output_mode=OutputMode.REPLY),
        chunks=["first", "second"],
    )

    async def cancel_after_first_delta() -> None:
        """Advance through the first delta and close the Agent generator."""

        stream = agent.stream_chat(_context())
        assert isinstance(await anext(stream), AgentStatus)
        assert isinstance(await anext(stream), AgentStatus)
        assert isinstance(await anext(stream), AgentDelta)
        await stream.aclose()

    asyncio.run(cancel_after_first_delta())

    assert specialists[SpecialistId.RESUME].streams[0].closed is True


def test_cover_letter_artifact_exposes_status_but_no_delta() -> None:
    """Hide Artifact chunks while returning one complete validated draft."""

    agent, _planner, _specialists_map = _job_agent(
        plan=ChatPlan(
            specialist=SpecialistId.COVER_LETTER,
            output_mode=OutputMode.ARTIFACT,
        ),
        chunks=["# Cover Letter", "\n\nDear Hiring Manager"],
    )

    events = asyncio.run(_collect_events(agent.stream_chat(_context())))

    assert not any(isinstance(event, AgentDelta) for event in events)
    statuses = [event for event in events if isinstance(event, AgentStatus)]
    assert [event.stage for event in statuses] == [
        "routing",
        "generating_artifact",
        "finalizing",
    ]
    assert statuses[1].artifact_type is ArtifactType.COVER_LETTER
    completed = cast(AgentCompleted, events[-1]).execution.content
    assert isinstance(completed, CreateArtifactResult)
    assert completed.draft == "# Cover Letter\n\nDear Hiring Manager"
    assert completed.artifact_type is ArtifactType.COVER_LETTER


@pytest.mark.parametrize(
    ("artifact_type", "specialist_id", "existing_types", "expected_type"),
    [
        (ArtifactType.CV, SpecialistId.RESUME, (), CreateArtifactResult),
        (
            ArtifactType.CV,
            SpecialistId.RESUME,
            (ArtifactType.CV,),
            UpdateArtifactResult,
        ),
        (
            ArtifactType.COVER_LETTER,
            SpecialistId.COVER_LETTER,
            (),
            CreateArtifactResult,
        ),
        (
            ArtifactType.COVER_LETTER,
            SpecialistId.COVER_LETTER,
            (ArtifactType.COVER_LETTER,),
            UpdateArtifactResult,
        ),
    ],
)
def test_artifact_stream_uses_only_same_type_existing_artifact(
    artifact_type: ArtifactType,
    specialist_id: SpecialistId,
    existing_types: tuple[ArtifactType, ...],
    expected_type: type[CreateArtifactResult] | type[UpdateArtifactResult],
) -> None:
    """Preserve create/update normalization from the same Artifact slot only."""

    agent, _planner, _specialists_map = _job_agent(
        plan=ChatPlan(specialist=specialist_id, output_mode=OutputMode.ARTIFACT),
        chunks=["# Complete draft"],
    )

    events = asyncio.run(
        _collect_events(agent.stream_chat(_context(existing_types=existing_types)))
    )

    result = cast(AgentCompleted, events[-1]).execution.content
    assert isinstance(result, expected_type)
    assert result.artifact_type is artifact_type
    assert result.draft == "# Complete draft"


def test_every_workspace_message_uses_chat_planner() -> None:
    """Route every v4 message through the conversational planner."""

    agent, planner, specialists = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.JOB_ANALYSIS, output_mode=OutputMode.REPLY),
        chunks=["# Analysis"],
    )

    events = asyncio.run(
        _collect_events(agent.stream_chat(_context(message="Analyze this role.")))
    )

    assert planner.calls[0].current_message == "Analyze this role."
    assert specialists[SpecialistId.JOB_ANALYSIS].calls
    assert any(isinstance(event, AgentDelta) for event in events)


@pytest.mark.parametrize(
    ("chunks", "message"),
    [([], "must contain Markdown"), ([" \n\t"], "must contain Markdown")],
)
def test_stream_rejects_empty_content_without_terminal_event(
    chunks: list[str],
    message: str,
) -> None:
    """Reject an empty reply before constructing an invalid terminal result."""

    agent, _planner, _specialists_map = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.GENERAL_QA, output_mode=OutputMode.REPLY),
        chunks=chunks,
    )

    with pytest.raises(job_match_agent_module.JobMatchOrchestrationError, match=message):
        asyncio.run(_collect_events(agent.stream_chat(_context())))


@pytest.mark.parametrize("mode", [OutputMode.REPLY, OutputMode.ARTIFACT])
def test_stream_rejects_content_over_document_limit(mode: OutputMode) -> None:
    """Stop accumulation once raw Markdown exceeds the shared 100k cap."""

    specialist = SpecialistId.RESUME if mode is OutputMode.ARTIFACT else SpecialistId.GENERAL_QA
    agent, _planner, specialists = _job_agent(
        plan=ChatPlan(specialist=specialist, output_mode=mode),
        chunks=["x" * DOCUMENT_TEXT_MAX_CHARS, "y"],
    )

    with pytest.raises(job_match_agent_module.JobMatchOrchestrationError, match="100000"):
        asyncio.run(_collect_events(agent.stream_chat(_context())))

    assert specialists[specialist].streams[0].closed is True


def test_sequential_sync_requests_do_not_reuse_an_owned_client_across_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close internally-owned async clients before each asyncio.run loop exits."""

    clients: list[LoopBoundAsyncClient] = []

    def build_client(**_kwargs: object) -> LoopBoundAsyncClient:
        """Create and record one internally-owned loop-bound async client."""

        client = LoopBoundAsyncClient()
        clients.append(client)
        return client

    monkeypatch.setattr("app.agents.base.AsyncOpenAI", build_client)
    agent = JobMatchAgent(model="loop-model")

    first = agent.handle_chat(_context(message="First request"))
    second = agent.handle_chat(_context(message="Second request"))

    assert first.content == ReplyResult(type="reply", markdown="## Answer")
    assert second.content == ReplyResult(type="reply", markdown="## Answer")
    assert len(clients) == 2
    assert all(client.closed for client in clients)


@pytest.mark.parametrize(
    ("lang", "existing", "expected_title", "expected_note"),
    [
        ("en", False, "Tailored CV", "Created the tailored CV."),
        ("en", True, "Tailored CV", "Updated the tailored CV."),
        ("zh", False, "定制简历", "已创建定制简历。"),
        ("zh", True, "定制简历", "已更新定制简历。"),
    ],
)
def test_artifact_titles_and_completion_notes_are_deterministic(
    lang: str,
    existing: bool,
    expected_title: str,
    expected_note: str,
) -> None:
    """Own localized Artifact metadata outside the model stream."""

    agent, _planner, _specialists_map = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.RESUME, output_mode=OutputMode.ARTIFACT),
        chunks=["# Candidate"],
    )

    events = asyncio.run(
        _collect_events(
            agent.stream_chat(
                _context(
                    lang=lang,
                    existing_types=(ArtifactType.CV,) if existing else (),
                )
            )
        )
    )

    result = cast(AgentCompleted, events[-1]).execution.content
    assert result.title == expected_title
    assert result.markdown == expected_note


def test_terminal_execution_reports_specialist_model_prompt_and_raw_payload() -> None:
    """Keep final streamed model metadata on the sole terminal execution."""

    agent, _planner, _specialists_map = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.RESUME, output_mode=OutputMode.REPLY),
        chunks=["first", " second"],
        model="final-specialist-model",
    )

    events = asyncio.run(_collect_events(agent.stream_chat(_context())))

    completed_events = [event for event in events if isinstance(event, AgentCompleted)]
    assert len(completed_events) == 1
    execution = completed_events[0].execution
    assert execution.model == "final-specialist-model"
    assert execution.prompt == "resume-prompt"
    assert execution.raw_result == "first second"


def test_anonymous_workspace_resolves_local_cv_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep anonymous streaming Specialists aligned with Quick Insight CV fallback."""

    agent, _planner, specialists = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.GENERAL_QA, output_mode=OutputMode.REPLY),
        chunks=["answer"],
    )
    monkeypatch.setattr(agent, "_read_cv", lambda: "# Anonymous Local CV")

    prepared = agent.prepare_workspace_context(_context(resume_text=None))
    asyncio.run(_collect_events(agent.stream_chat(prepared)))

    called_context = specialists[SpecialistId.GENERAL_QA].calls[0][0]
    assert called_context.resume_text == "# Anonymous Local CV"


def test_orchestrator_does_not_cache_request_state() -> None:
    """Retain only injected collaborators across independent streams."""

    agent, _planner, _specialists_map = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.GENERAL_QA, output_mode=OutputMode.REPLY),
        chunks=["answer"],
    )

    asyncio.run(_collect_events(agent.stream_chat(_context(message="First request"))))
    asyncio.run(_collect_events(agent.stream_chat(_context(message="Second request"))))

    assert not {
        "context",
        "request",
        "resume_text",
        "histories",
        "artifacts",
        "current_message",
    }.intersection(vars(agent))
