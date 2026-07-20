"""Facade/Mediator tests for stateless Job Match Workspace orchestration."""

from collections.abc import Mapping
from uuid import uuid4

import pytest

import app.agents.job_match.agent as job_match_agent_module
from app.agents.base import AgentExecution, WorkspaceAgentContext
from app.agents.job_match import JobMatchAgent
from app.agents.job_match.context import JobChatContext
from app.agents.job_match.router import RouteDecision, SpecialistId
from app.agents.job_match.specialists.base import (
    ArtifactDraftResult,
    JobMatchSpecialist,
    SpecialistReply,
    SpecialistResult,
)
from app.modules.task.schema import (
    ActionId,
    Artifact,
    ArtifactType,
    Artifacts,
    Attachment,
    CreateArtifactResult,
    HistoryMessage,
    QuickInsightActionWorkspaceRequest,
    ReplyResult,
    UpdateArtifactResult,
    UserMessageWorkspaceRequest,
    WorkspaceResultType,
    WorkspaceTrigger,
)


LONG_JD = (
    "Senior Backend Engineer responsible for distributed Go services, APIs, "
    "Kubernetes, observability, reliability, and cross-team architecture. "
) * 12


class SpyRouter:
    """Record routing calls while returning one deterministic Specialist choice."""

    def __init__(
        self,
        specialist: SpecialistId = SpecialistId.GENERAL_QA,
        *,
        events: list[str] | None = None,
    ) -> None:
        """Configure the selected Specialist and optional shared event log."""

        self.specialist = specialist
        self.events = events
        self.calls: list[JobChatContext] = []

    def route(self, context: JobChatContext) -> RouteDecision:
        """Record one immutable context and return the configured decision."""

        self.calls.append(context)
        if self.events is not None:
            self.events.append("router")
        return RouteDecision(specialist=self.specialist)


class SpySpecialist(JobMatchSpecialist):
    """Record Strategy calls while returning one prepared execution."""

    def __init__(
        self,
        content: SpecialistResult | object,
        *,
        name: str,
        events: list[str] | None = None,
        model: str | None = None,
    ) -> None:
        """Configure the prepared content and observable execution metadata."""

        self.content = content
        self.name = name
        self.events = events
        self.model = model or f"{name}-model"
        self.calls: list[JobChatContext] = []

    def handle(self, context: JobChatContext) -> AgentExecution[SpecialistResult]:
        """Record one context and expose the configured Specialist execution."""

        self.calls.append(context)
        if self.events is not None:
            self.events.append(self.name)
        return AgentExecution(
            content=self.content,  # type: ignore[arg-type]
            raw_result=f"{self.name}-raw",
            prompt=f"{self.name}-prompt",
            model=self.model,
        )


def _reply(markdown: str = "## Answer\n\nUse the strongest evidence.") -> SpecialistReply:
    """Build one legal Specialist reply."""

    return SpecialistReply(type="reply", markdown=markdown)


def _draft(artifact_type: ArtifactType) -> ArtifactDraftResult:
    """Build one complete legal Specialist Artifact draft."""

    if artifact_type is ArtifactType.CV:
        return ArtifactDraftResult(
            type="artifact_draft",
            markdown="Created the tailored CV.",
            artifact_type=artifact_type,
            title="Tailored CV",
            draft="# Candidate\n\n## Experience\n\nBuilt distributed Go services.",
        )
    return ArtifactDraftResult(
        type="artifact_draft",
        markdown="Created the cover letter.",
        artifact_type=artifact_type,
        title="Cover Letter",
        draft="# Cover Letter\n\nDear Hiring Manager,\n\nI built Go services.",
    )


def _artifact_state(
    *existing_types: ArtifactType,
) -> tuple[Artifacts, list[HistoryMessage]]:
    """Build valid current Artifact snapshots and their latest message Attachments."""

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
        lang="en",
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
    analysis: SpecialistResult | object | None = None,
    resume: SpecialistResult | object | None = None,
    cover_letter: SpecialistResult | object | None = None,
    general_qa: SpecialistResult | object | None = None,
    events: list[str] | None = None,
) -> Mapping[SpecialistId, SpySpecialist]:
    """Build an injectable complete Specialist Strategy map."""

    return {
        SpecialistId.JOB_ANALYSIS: SpySpecialist(
            analysis or _reply(), name="analysis", events=events
        ),
        SpecialistId.RESUME: SpySpecialist(
            resume or _reply(), name="resume", events=events
        ),
        SpecialistId.COVER_LETTER: SpySpecialist(
            cover_letter or _reply(), name="cover_letter", events=events
        ),
        SpecialistId.GENERAL_QA: SpySpecialist(
            general_qa or _reply(), name="general_qa", events=events
        ),
    }


def test_normal_message_invokes_router_then_exactly_one_specialist() -> None:
    """Route a user message before calling only the selected Strategy."""

    events: list[str] = []
    router = SpyRouter(SpecialistId.GENERAL_QA, events=events)
    specialists = _specialists(events=events)
    agent = JobMatchAgent(intent_router=router, specialists=specialists)

    execution = agent.handle_chat(_context(message="What does ATS mean?"))

    assert events == ["router", "general_qa"]
    assert len(router.calls) == 1
    assert sum(len(specialist.calls) for specialist in specialists.values()) == 1
    assert isinstance(execution.content, ReplyResult)


def test_anonymous_workspace_resolves_the_configured_local_cv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep anonymous Workspace specialists aligned with Quick Insight CV fallback."""

    specialists = _specialists()
    agent = JobMatchAgent(
        intent_router=SpyRouter(SpecialistId.GENERAL_QA),
        specialists=specialists,
    )
    monkeypatch.setattr(agent, "_read_cv", lambda: "# Anonymous Local CV")

    agent.handle_chat(_context(resume_text=None))

    assert specialists[SpecialistId.GENERAL_QA].calls[0].resume_text == (
        "# Anonymous Local CV"
    )


def test_selected_action_is_a_hint_and_does_not_force_an_artifact() -> None:
    """Keep a normal-message result under Router and Specialist semantic control."""

    router = SpyRouter(SpecialistId.RESUME)
    specialists = _specialists(resume=_reply("## CV advice\n\nEmphasize ownership."))
    agent = JobMatchAgent(intent_router=router, specialists=specialists)

    execution = agent.handle_chat(
        _context(
            action=ActionId.TAILOR_RESUME,
            message="What should I emphasize in my CV?",
        )
    )

    assert execution.content == ReplyResult(
        type=WorkspaceResultType.REPLY,
        markdown="## CV advice\n\nEmphasize ownership.",
    )


@pytest.mark.parametrize(
    ("action", "specialist_id", "specialist_result", "expected_result_type"),
    [
        (
            ActionId.ANALYZE,
            SpecialistId.JOB_ANALYSIS,
            _reply("## Analysis\n\nStrong backend match."),
            ReplyResult,
        ),
        (
            ActionId.TAILOR_RESUME,
            SpecialistId.RESUME,
            _draft(ArtifactType.CV),
            CreateArtifactResult,
        ),
        (
            ActionId.WRITE_COVER_LETTER,
            SpecialistId.COVER_LETTER,
            _draft(ArtifactType.COVER_LETTER),
            CreateArtifactResult,
        ),
    ],
)
def test_quick_commands_map_directly_to_deterministic_specialists(
    action: ActionId,
    specialist_id: SpecialistId,
    specialist_result: SpecialistResult,
    expected_result_type: type[ReplyResult] | type[CreateArtifactResult],
) -> None:
    """Execute each supported Quick command through its fixed Strategy mapping."""

    router = SpyRouter()
    specialists = _specialists(
        analysis=specialist_result if specialist_id is SpecialistId.JOB_ANALYSIS else None,
        resume=specialist_result if specialist_id is SpecialistId.RESUME else None,
        cover_letter=(
            specialist_result if specialist_id is SpecialistId.COVER_LETTER else None
        ),
    )
    agent = JobMatchAgent(intent_router=router, specialists=specialists)

    execution = agent.handle_chat(
        _context(action=action, trigger=WorkspaceTrigger.QUICK_INSIGHT_ACTION)
    )

    assert isinstance(execution.content, expected_result_type)
    assert len(specialists[specialist_id].calls) == 1


@pytest.mark.parametrize(
    "action",
    [
        ActionId.ANALYZE,
        ActionId.TAILOR_RESUME,
        ActionId.WRITE_COVER_LETTER,
        ActionId.ASK_MORE,
    ],
)
def test_every_quick_command_bypasses_intent_router(action: ActionId) -> None:
    """Prove all Quick command branches, including rejection, never call Router."""

    router = SpyRouter()
    specialists = _specialists(
        resume=_draft(ArtifactType.CV),
        cover_letter=_draft(ArtifactType.COVER_LETTER),
    )
    agent = JobMatchAgent(intent_router=router, specialists=specialists)
    context = _context(action=action, trigger=WorkspaceTrigger.QUICK_INSIGHT_ACTION)

    if action is ActionId.ASK_MORE:
        with pytest.raises(
            job_match_agent_module.JobMatchOrchestrationError,
            match="ask_more",
        ):
            agent.handle_chat(context)
    else:
        agent.handle_chat(context)

    assert router.calls == []
    if action is ActionId.ASK_MORE:
        assert all(specialist.calls == [] for specialist in specialists.values())


@pytest.mark.parametrize(
    ("artifact_type", "specialist_id", "existing_types", "expected_type"),
    [
        (
            ArtifactType.CV,
            SpecialistId.RESUME,
            (),
            CreateArtifactResult,
        ),
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
def test_artifact_draft_uses_only_same_type_existing_artifact(
    artifact_type: ArtifactType,
    specialist_id: SpecialistId,
    existing_types: tuple[ArtifactType, ...],
    expected_type: type[CreateArtifactResult] | type[UpdateArtifactResult],
) -> None:
    """Normalize a draft to create or update from the matching Artifact slot only."""

    specialist_result = _draft(artifact_type)
    specialists = _specialists(
        resume=specialist_result if specialist_id is SpecialistId.RESUME else None,
        cover_letter=(
            specialist_result if specialist_id is SpecialistId.COVER_LETTER else None
        ),
    )
    agent = JobMatchAgent(
        intent_router=SpyRouter(specialist_id),
        specialists=specialists,
    )

    execution = agent.handle_chat(
        _context(existing_types=existing_types, message="Create the complete artifact.")
    )

    assert isinstance(execution.content, expected_type)
    assert execution.content.artifact_type is artifact_type
    assert execution.content.title == specialist_result.title
    assert execution.content.draft == specialist_result.draft


@pytest.mark.parametrize(
    ("draft_type", "specialist_id", "other_type"),
    [
        (ArtifactType.CV, SpecialistId.RESUME, ArtifactType.COVER_LETTER),
        (
            ArtifactType.COVER_LETTER,
            SpecialistId.COVER_LETTER,
            ArtifactType.CV,
        ),
    ],
)
def test_other_artifact_type_does_not_turn_create_into_update(
    draft_type: ArtifactType,
    specialist_id: SpecialistId,
    other_type: ArtifactType,
) -> None:
    """Ignore the unrelated Artifact slot when selecting create versus update."""

    specialist_result = _draft(draft_type)
    specialists = _specialists(
        resume=specialist_result if specialist_id is SpecialistId.RESUME else None,
        cover_letter=(
            specialist_result if specialist_id is SpecialistId.COVER_LETTER else None
        ),
    )
    agent = JobMatchAgent(
        intent_router=SpyRouter(specialist_id),
        specialists=specialists,
    )

    execution = agent.handle_chat(
        _context(existing_types=(other_type,), message="Create the complete artifact.")
    )

    assert isinstance(execution.content, CreateArtifactResult)


@pytest.mark.parametrize(
    ("specialist_id", "illegal_result"),
    [
        (SpecialistId.JOB_ANALYSIS, _draft(ArtifactType.CV)),
        (SpecialistId.RESUME, _draft(ArtifactType.COVER_LETTER)),
        (SpecialistId.COVER_LETTER, _draft(ArtifactType.CV)),
        (SpecialistId.GENERAL_QA, _draft(ArtifactType.COVER_LETTER)),
        (SpecialistId.GENERAL_QA, object()),
    ],
)
def test_illegal_specialist_result_matrix_raises_orchestration_error(
    specialist_id: SpecialistId,
    illegal_result: SpecialistResult | object,
) -> None:
    """Enforce the Facade's legal result matrix even for injected Strategies."""

    specialists = _specialists()
    specialists[specialist_id] = SpySpecialist(
        illegal_result,
        name=specialist_id.value,
    )
    agent = JobMatchAgent(
        intent_router=SpyRouter(specialist_id),
        specialists=specialists,
    )

    with pytest.raises(
        job_match_agent_module.JobMatchOrchestrationError,
        match="illegal Specialist result",
    ):
        agent.handle_chat(_context())


@pytest.mark.parametrize(
    ("action", "specialist_id", "illegal_result"),
    [
        (ActionId.ANALYZE, SpecialistId.JOB_ANALYSIS, _draft(ArtifactType.CV)),
        (ActionId.TAILOR_RESUME, SpecialistId.RESUME, _reply()),
        (ActionId.WRITE_COVER_LETTER, SpecialistId.COVER_LETTER, _reply()),
    ],
)
def test_quick_commands_enforce_the_stricter_result_matrix(
    action: ActionId,
    specialist_id: SpecialistId,
    illegal_result: SpecialistResult,
) -> None:
    """Require each deterministic command to return its exact expected result kind."""

    specialists = _specialists()
    specialists[specialist_id] = SpySpecialist(
        illegal_result,
        name=specialist_id.value,
    )
    agent = JobMatchAgent(intent_router=SpyRouter(), specialists=specialists)

    with pytest.raises(
        job_match_agent_module.JobMatchOrchestrationError,
        match="Quick Insight Action",
    ):
        agent.handle_chat(
            _context(action=action, trigger=WorkspaceTrigger.QUICK_INSIGHT_ACTION)
        )


def test_agent_execution_reports_final_specialist_model_and_payload() -> None:
    """Keep the final Strategy's model, prompt, and raw output on AgentExecution."""

    specialists = _specialists()
    specialists[SpecialistId.RESUME] = SpySpecialist(
        _reply(),
        name="resume",
        model="final-specialist-model",
    )
    agent = JobMatchAgent(
        intent_router=SpyRouter(SpecialistId.RESUME),
        specialists=specialists,
    )

    execution = agent.handle_chat(_context())

    assert execution.model == "final-specialist-model"
    assert execution.prompt == "resume-prompt"
    assert execution.raw_result == "resume-raw"


def test_orchestrator_does_not_cache_request_state() -> None:
    """Retain only injected collaborators across independent request executions."""

    agent = JobMatchAgent(
        intent_router=SpyRouter(),
        specialists=_specialists(),
    )

    agent.handle_chat(_context(message="First request"))
    agent.handle_chat(_context(message="Second request"))

    assert not {
        "context",
        "request",
        "resume_text",
        "histories",
        "artifacts",
        "selected_action",
        "current_message",
    }.intersection(vars(agent))
