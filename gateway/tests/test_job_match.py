from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

import app.agents.job_match as job_match_package
from app.agents.base import AgentContext, QuickInsightAgent
from app.agents.job_match import MIN_JOB_CONTENT_CHARS, JobMatchAgent
from app.agents.job_match.context import JobChatContext
from app.modules.task.schema import (
    ActionId,
    AgentName,
    Artifacts,
    DetailsInsightCard,
    QuickInsightActionWorkspaceRequest,
    QuickInsightRequest,
    ScoreInsightCard,
    TaskRequest,
    TextInsightCard,
    WorkspaceTrigger,
)
from app.modules.task.service import TaskService


LONG_JD = (
    "Senior Backend Engineer — responsibilities include designing distributed systems, "
    "building gRPC and REST APIs, operating Kubernetes, databases, queues, observability, "
    "and scaling production services. Requirements include 5+ years of backend engineering, "
    "expert Go skills, reliability ownership, performance tuning, and cross-team architecture. "
) * 4
assert len(LONG_JD) >= MIN_JOB_CONTENT_CHARS


def fake_client(content: str, captured: dict | None = None):
    """Build an OpenAI-compatible fake returning one fixed completion."""

    def create(**kwargs):
        """Capture one model request and return the configured response."""

        if captured is not None:
            captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def quick_request(**updates) -> QuickInsightRequest:
    """Build a valid job Quick Insight request with optional overrides."""

    values = dict(
        url="https://www.linkedin.com/jobs/view/1",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
    )
    values.update(updates)
    return QuickInsightRequest(**values)


def task_request(action_id: str = "deep_analysis", **updates) -> TaskRequest:
    """Build a valid legacy `/tasks` request with optional overrides."""

    values = dict(
        url="https://www.linkedin.com/jobs/view/1",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        actionId=action_id,
    )
    values.update(updates)
    return TaskRequest(**values)


def test_package_preserves_public_import_surface() -> None:
    """Expose the historical Agent and routing constant from the new package."""

    assert job_match_package.JobMatchAgent is JobMatchAgent
    assert job_match_package.MIN_JOB_CONTENT_CHARS is MIN_JOB_CONTENT_CHARS
    assert hasattr(job_match_package, "__path__")


def test_job_chat_context_is_immutable_and_request_scoped() -> None:
    """Keep all future Workspace state in one frozen request context."""

    request = QuickInsightActionWorkspaceRequest(
        trigger=WorkspaceTrigger.QUICK_INSIGHT_ACTION,
        url="https://www.linkedin.com/jobs/view/1",
        resourceUrl="https://www.linkedin.com/jobs/view/1",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        actionId=ActionId.ANALYZE,
        artifacts=Artifacts(cv=None, cover_letter=None),
    )
    context = JobChatContext(
        trigger=request.trigger,
        request=request,
        resume_text="REQUEST CV",
        histories=tuple(request.histories),
        artifacts=request.artifacts,
        selected_action=request.action_id,
    )

    assert context.current_message is None
    assert context.histories == ()
    with pytest.raises(FrozenInstanceError):
        context.resume_text = "OTHER USER CV"


def test_job_match_declares_workspace_actions() -> None:
    """Expose the ordered stable Action ids declared by the job Agent."""

    agent = JobMatchAgent()
    ctx = AgentContext(request=quick_request(lang="en"), resume_text="CV")

    actions = agent.available_actions(ctx)

    assert isinstance(agent, QuickInsightAgent)
    assert agent.actions(ctx) == actions
    assert [action.id for action in actions] == [
        ActionId.ANALYZE,
        ActionId.TAILOR_RESUME,
        ActionId.WRITE_COVER_LETTER,
        ActionId.ASK_MORE,
    ]
    assert [action.title for action in actions] == [
        "Analyze",
        "Tailor Resume",
        "Generate Cover Letter",
        "Ask More",
    ]


def test_quick_insight_returns_decision_overview_strength_and_gap() -> None:
    """Parse every decision-first Quick Insight field into typed cards."""

    captured: dict = {}
    result = (
        '@@INSIGHT\n{"score":87,"recommendation":"apply",'
        '"reason":"Core requirements match.","industry_business":"Fintech",'
        '"role_focus":"Backend","summary":"Build payment services.",'
        '"top_strength":"Go ownership","top_gap":"Payments depth"}'
    )
    agent = JobMatchAgent(client=fake_client(result, captured), model="m")

    execution = agent.quick_insight(
        AgentContext(request=quick_request(lang="en"), resume_text="REQUEST CV")
    )

    assert execution.content.title == "Job Match"
    decision = execution.content.cards[0]
    overview = execution.content.cards[1]
    strength = execution.content.cards[2]
    gap = execution.content.cards[3]
    assert isinstance(decision, ScoreInsightCard)
    assert (decision.score, decision.recommendation, decision.reason) == (
        87,
        "apply",
        "Core requirements match.",
    )
    assert isinstance(overview, DetailsInsightCard)
    assert [item.value for item in overview.items] == ["Fintech", "Backend"]
    assert overview.summary == "Build payment services."
    assert isinstance(strength, TextInsightCard)
    assert "Go ownership" in strength.body_html
    assert isinstance(gap, TextInsightCard)
    assert "Payments depth" in gap.body_html
    assert "REQUEST CV" in captured["messages"][1]["content"]


@pytest.mark.parametrize(
    "raw",
    [
        "@@INSIGHT\nnot json",
        "@@INSIGHT\n[]",
        '@@INSIGHT\n{"score":101,"recommendation":"apply"}',
        'preface\n@@INSIGHT\n{"score":87}',
    ],
)
def test_quick_insight_rejects_invalid_contract(raw: str) -> None:
    """Reject malformed, incomplete, or out-of-range model payloads."""

    agent = JobMatchAgent(client=fake_client(raw), model="m")

    with pytest.raises(ValueError, match="Quick Insight"):
        agent.quick_insight(AgentContext(request=quick_request(), resume_text="CV"))


def test_validation_rejects_short_selection_before_model_call() -> None:
    """Reject sparse job evidence even when the full page body is long."""

    agent = JobMatchAgent()
    request = quick_request(selectedText="short", pageText="x" * 5000)

    with pytest.raises(ValueError, match="职位描述太少"):
        agent.validate(AgentContext(request=request, resume_text="CV"))


def test_quick_insight_service_routes_agent_and_injects_user_resume() -> None:
    """Route job Quick Insight and inject only the current user's resume."""

    captured: dict = {}
    result = (
        '@@INSIGHT\n{"score":87,"recommendation":"apply",'
        '"reason":"Core requirements match.","industry_business":"Fintech",'
        '"role_focus":"Backend","summary":"Build payments.",'
        '"top_strength":"Go","top_gap":"Payments"}'
    )

    class ResumeService:
        """Return one active resume for the authenticated test user."""

        def active_resume_text(self, *, user_id: str) -> str:
            """Resolve the current user's request-scoped resume text."""

            assert user_id == "user-1"
            return "INJECTED USER CV"

    agent = JobMatchAgent(client=fake_client(result, captured), model="m")
    service = TaskService(
        agents={AgentName.JOB_MATCH: agent},
        repository=None,
        resume_service=ResumeService(),
        default_model="m",
    )

    response = service.quick_insight(quick_request(), user_id="user-1")

    assert response.workspace.default_action_id == "analyze"
    assert isinstance(response.insight.cards[0], ScoreInsightCard)
    assert "INJECTED USER CV" in captured["messages"][1]["content"]
    assert not hasattr(agent, "_cv_text")


def test_temporary_legacy_delegate_returns_old_task_response() -> None:
    """Keep `/tasks` document execution runnable until the Task 8 protocol shim."""

    captured: dict = {}

    class ResumeService:
        """Return one active resume for the authenticated legacy request."""

        def active_resume_text(self, *, user_id: str) -> str:
            """Resolve the current user's request-scoped legacy resume text."""

            assert user_id == "legacy-user"
            return "LEGACY REQUEST CV"

    agent = JobMatchAgent(
        client=fake_client("@@SECTION cover_letter\nDear Hiring Manager", captured),
        model="m",
    )
    service = TaskService(
        agents={AgentName.JOB_MATCH: agent},
        repository=None,
        resume_service=ResumeService(),
        default_model="m",
    )
    request = task_request(
        "write_cover_letter",
        selectedText="",
        priorResult="@@SECTION conclusion\nMatch 82.",
    )

    response = service.execute(
        request,
        user_id="legacy-user",
        agent_override=AgentName.JOB_MATCH,
    )

    assert response.document.text.startswith("@@SECTION conclusion")
    assert [section.id for section in response.document.sections] == [
        "conclusion",
        "cover_letter",
    ]
    assert "LEGACY REQUEST CV" in captured["messages"][1]["content"]
    assert not hasattr(agent, "_cv_text")
