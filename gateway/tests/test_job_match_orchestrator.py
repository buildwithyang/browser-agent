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
    ActionId,
    Artifact,
    ArtifactType,
    Artifacts,
    Attachment,
    CreateArtifactResult,
    DOCUMENT_TEXT_MAX_CHARS,
    HistoryMessage,
    QuickInsightActionWorkspaceRequest,
    ReplyResult,
    UpdateArtifactResult,
    UserMessageWorkspaceRequest,
    WorkspaceTrigger,
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


class SpySpecialist:
    """Record Strategy calls while returning a prepared Markdown stream."""

    def __init__(
        self,
        chunks: list[str],
        *,
        name: str,
        model: str | None = None,
    ) -> None:
        """Configure raw chunks and observable execution metadata."""

        self.chunks = chunks
        self.name = name
        self.model = model or f"{name}-model"
        self.calls: list[tuple[JobChatContext, OutputMode]] = []

    async def open_stream(
        self,
        context: JobChatContext,
        output_mode: OutputMode,
    ) -> object:
        """Record one request and expose the configured raw Markdown stream."""

        self.calls.append((context, output_mode))

        async def generate() -> AsyncIterator[str]:
            """Yield configured chunks exactly once in order."""

            for chunk in self.chunks:
                yield chunk

        return SimpleNamespace(
            prompt=f"{self.name}-prompt",
            model=self.model,
            chunks=generate(),
        )


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
    action: ActionId = ActionId.ANALYZE,
    trigger: WorkspaceTrigger = WorkspaceTrigger.USER_MESSAGE,
    message: str = "What should I emphasize?",
    existing_types: tuple[ArtifactType, ...] = (),
    resume_text: str | None = "# Canonical Resume",
    lang: str = "en",
) -> WorkspaceAgentContext:
    """Build one valid immutable v2 Workspace Agent context."""

    artifacts, histories = _artifact_state(*existing_types)
    common = dict(
        trigger=trigger,
        url="https://www.linkedin.com/jobs/view/123",
        resourceUrl="https://www.linkedin.com/jobs/view/123",
        operationId="00000000-0000-0000-0000-000000000001",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        pageText="Full job page.",
        lang=lang,
        actionId=action,
        histories=histories,
        artifacts=artifacts,
    )
    if trigger is WorkspaceTrigger.USER_MESSAGE:
        request = UserMessageWorkspaceRequest(**common, message=message)
    else:
        request = QuickInsightActionWorkspaceRequest(**common)
    return WorkspaceAgentContext(request=request, resume_text=resume_text)


def _specialists(
    *,
    chunks: list[str],
    selected: SpecialistId,
    model: str | None = None,
) -> Mapping[SpecialistId, SpySpecialist]:
    """Build a complete injectable Strategy registry with one selected output."""

    return {
        specialist_id: SpySpecialist(
            chunks if specialist_id is selected else ["unexpected"],
            name=specialist_id.value,
            model=model if specialist_id is selected else None,
        )
        for specialist_id in SpecialistId
    }


def _job_agent(
    *,
    plan: ChatPlan,
    chunks: list[str],
    model: str | None = None,
) -> tuple[JobMatchAgent, SpyPlanner, Mapping[SpecialistId, SpySpecialist]]:
    """Build one streaming Facade and its observable collaborators."""

    planner = SpyPlanner(plan)
    specialists = _specialists(chunks=chunks, selected=plan.specialist, model=model)
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


@pytest.mark.parametrize(
    ("action", "specialist_id", "output_mode", "expects_delta"),
    [
        (ActionId.ANALYZE, SpecialistId.JOB_ANALYSIS, OutputMode.REPLY, True),
        (ActionId.TAILOR_RESUME, SpecialistId.RESUME, OutputMode.ARTIFACT, False),
        (
            ActionId.WRITE_COVER_LETTER,
            SpecialistId.COVER_LETTER,
            OutputMode.ARTIFACT,
            False,
        ),
    ],
)
def test_quick_actions_use_deterministic_plan_and_bypass_planner(
    action: ActionId,
    specialist_id: SpecialistId,
    output_mode: OutputMode,
    expects_delta: bool,
) -> None:
    """Map backend Quick commands directly to fixed Specialist/output pairs."""

    agent, planner, specialists = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.GENERAL_QA, output_mode=OutputMode.REPLY),
        chunks=["# Generated content"],
    )
    specialists[specialist_id].chunks = ["# Deterministic content"]

    events = asyncio.run(
        _collect_events(
            agent.stream_chat(
                _context(action=action, trigger=WorkspaceTrigger.QUICK_INSIGHT_ACTION)
            )
        )
    )

    assert planner.calls == []
    assert specialists[specialist_id].calls[0][1] is output_mode
    assert any(isinstance(event, AgentDelta) for event in events) is expects_delta


def test_quick_ask_more_rejects_without_planner_or_specialist() -> None:
    """Reject the UI-only Quick Action before any model dependency is called."""

    agent, planner, specialists = _job_agent(
        plan=ChatPlan(specialist=SpecialistId.GENERAL_QA, output_mode=OutputMode.REPLY),
        chunks=["unexpected"],
    )

    with pytest.raises(job_match_agent_module.JobMatchOrchestrationError, match="ask_more"):
        asyncio.run(
            _collect_events(
                agent.stream_chat(
                    _context(
                        action=ActionId.ASK_MORE,
                        trigger=WorkspaceTrigger.QUICK_INSIGHT_ACTION,
                    )
                )
            )
        )

    assert planner.calls == []
    assert all(specialist.calls == [] for specialist in specialists.values())


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
    agent, _planner, _specialists_map = _job_agent(
        plan=ChatPlan(specialist=specialist, output_mode=mode),
        chunks=["x" * DOCUMENT_TEXT_MAX_CHARS, "y"],
    )

    with pytest.raises(job_match_agent_module.JobMatchOrchestrationError, match="100000"):
        asyncio.run(_collect_events(agent.stream_chat(_context())))


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

    asyncio.run(_collect_events(agent.stream_chat(_context(resume_text=None))))

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
        "selected_action",
        "current_message",
    }.intersection(vars(agent))
