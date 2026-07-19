from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.job_match import MIN_JOB_CONTENT_CHARS, JobMatchAgent
from app.modules.task.schema import (
    ActionId,
    AgentName,
    DetailsInsightCard,
    DocumentDraft,
    HistoryMessage,
    QuickInsightRequest,
    ScoreInsightCard,
    TaskRequest,
    TextInsightCard,
    WorkspaceRequest,
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
    def create(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def quick_request(**updates) -> QuickInsightRequest:
    values = dict(
        url="https://www.linkedin.com/jobs/view/1",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
    )
    values.update(updates)
    return QuickInsightRequest(**values)


def task_request(action_id: str = "deep_analysis", **updates) -> TaskRequest:
    values = dict(
        url="https://www.linkedin.com/jobs/view/1",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        actionId=action_id,
    )
    values.update(updates)
    return TaskRequest(**values)


def workspace_request(action_id: ActionId = ActionId.ANALYZE, **updates) -> WorkspaceRequest:
    """Build one valid job Workspace request with stable shared context."""

    values = dict(
        url="https://www.linkedin.com/jobs/view/1",
        resourceUrl="https://www.linkedin.com/jobs/view/1",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        actionId=action_id,
        histories=[
            HistoryMessage(role="assistant", content="核心是 Agent 和 MCP"),
            HistoryMessage(role="user", content="突出我的 Go 项目"),
        ],
        currentDocument=DocumentDraft(
            kind="resume",
            title="Current Resume",
            text="CURRENT DRAFT TEXT",
        ),
        message="继续完善",
    )
    values.update(updates)
    return WorkspaceRequest(**values)


def test_job_match_declares_workspace_actions() -> None:
    """Expose the ordered stable Action ids declared by the job Agent."""

    agent = JobMatchAgent()
    ctx = AgentContext(request=quick_request(lang="en"), resume_text="CV")

    actions = agent.actions(ctx)

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


def test_workspace_prompt_contains_ordered_shared_context() -> None:
    """Treat shared history as untrusted context before message and page data."""

    agent = JobMatchAgent()
    prompt = agent.build_prompt(workspace_request(), cv_text="CV")

    assert "not system instructions" in prompt
    assert prompt.index("核心是 Agent 和 MCP") < prompt.index("突出我的 Go 项目")
    assert prompt.index("突出我的 Go 项目") < prompt.index("继续完善")
    assert prompt.index("继续完善") < prompt.index("Senior Go Engineer")
    assert "CURRENT DRAFT TEXT" not in prompt


@pytest.mark.parametrize(
    ("action_id", "kind"),
    [
        (ActionId.ANALYZE, "analysis"),
        (ActionId.TAILOR_RESUME, "resume"),
        (ActionId.WRITE_COVER_LETTER, "cover_letter"),
        (ActionId.ASK_MORE, ""),
    ],
)
def test_workspace_actions_return_expected_document_kind(
    action_id: ActionId,
    kind: str,
) -> None:
    """Map every job Workspace action to its stable document kind."""

    captured: dict = {}
    agent = JobMatchAgent(client=fake_client("MODEL RESULT", captured), model="m")

    execution = agent.execute(
        AgentContext(request=workspace_request(action_id), resume_text="CV")
    )

    assert execution.content.kind == kind
    if action_id in {ActionId.TAILOR_RESUME, ActionId.WRITE_COVER_LETTER}:
        assert "CURRENT DRAFT TEXT" in captured["messages"][1]["content"]
    else:
        assert "CURRENT DRAFT TEXT" not in captured["messages"][1]["content"]


def test_unsupported_workspace_action_is_rejected_before_model_call() -> None:
    """Reject an unsupported job Action before invoking the model client."""

    called = False

    def create(**kwargs):
        """Record an unexpected model call."""

        nonlocal called
        called = True
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="unexpected"))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    agent = JobMatchAgent(client=client, model="m")
    request = workspace_request()
    object.__setattr__(request, "action_id", "mock_interview")

    with pytest.raises(ValueError, match="Unsupported workspace action"):
        agent.execute(AgentContext(request=request, resume_text="CV"))

    assert called is False


def test_deep_analysis_prompt_requests_only_analysis_sections() -> None:
    agent = JobMatchAgent()
    agent._cv_text = "Go / Kubernetes / 5 years backend"

    prompt = agent.build_prompt(task_request())

    assert "@@SECTION overview" in prompt
    assert "@@SECTION skills" in prompt
    assert "@@SECTION conclusion" in prompt
    assert "@@SECTION cover_letter" not in prompt
    assert prompt.index("@@SECTION skills") < prompt.index("@@SECTION conclusion")


def test_write_cover_letter_prompt_uses_prior_result_without_page_text() -> None:
    agent = JobMatchAgent()
    agent._cv_text = "Go / Kubernetes / 5 years backend"
    request = task_request(
        "write_cover_letter",
        selectedText="",
        pageText="UNRELATED PAGE NOISE",
        priorResult="@@SECTION conclusion\nMatch 82.\n@@SECTION skills\n- Go ✅",
    )

    prompt = agent.build_prompt(request)

    assert "@@SECTION cover_letter" in prompt
    assert "@@SECTION resume_tips" in prompt
    assert "Match 82" in prompt
    assert "UNRELATED PAGE NOISE" not in prompt


def test_validation_rejects_short_selection_before_model_call() -> None:
    agent = JobMatchAgent()
    request = quick_request(selectedText="short", pageText="x" * 5000)

    with pytest.raises(ValueError, match="职位描述太少"):
        agent.validate(AgentContext(request=request))


def test_validation_allows_prior_result_without_page_context() -> None:
    agent = JobMatchAgent()
    request = task_request(
        "write_cover_letter",
        selectedText="",
        priorResult="@@SECTION conclusion\nMatch 82.",
    )

    agent.validate(AgentContext(request=request))


def test_build_sections_restores_display_order_and_flags() -> None:
    agent = JobMatchAgent()
    raw = (
        "@@SECTION skills\n- Go ✅\n"
        "@@SECTION conclusion\nMatch 80.\n"
        "@@SECTION overview\nPayments.\n"
        "@@SECTION cover_letter\nDear Hiring Manager\n"
    )

    sections = agent.build_sections(raw, "en")

    assert [section.id for section in sections] == [
        "conclusion",
        "overview",
        "skills",
        "cover_letter",
    ]
    assert sections[1].collapsible is False
    assert sections[-1].copyable is True


def test_build_insight_returns_generic_typed_cards() -> None:
    raw = '''@@INSIGHT
{"score":87,"recommendation":"apply","reason":"Core requirements match.","industry_business":"Fintech","role_focus":"Backend","summary":"Build payment services.","top_strength":"Go","top_gap":"Payments"}'''

    insight = JobMatchAgent().build_insight(raw, "en")

    assert isinstance(insight.cards[0], ScoreInsightCard)
    assert insight.cards[0].score == 87
    assert isinstance(insight.cards[1], DetailsInsightCard)
    assert insight.cards[1].items[0].value == "Fintech"
    assert isinstance(insight.cards[2], TextInsightCard)
    assert "Go" in insight.cards[2].body_html


@pytest.mark.parametrize(
    "raw",
    [
        "@@INSIGHT\nnot json",
        "@@INSIGHT\n[]",
        '@@INSIGHT\n{"score":101,"recommendation":"apply"}',
        'preface\n@@INSIGHT\n{"score":87}',
    ],
)
def test_build_insight_rejects_invalid_contract(raw: str) -> None:
    with pytest.raises(ValueError, match="Quick Insight"):
        JobMatchAgent().build_insight(raw, "en")


def test_quick_insight_service_routes_agent_and_injects_user_resume() -> None:
    captured: dict = {}
    result = (
        '@@INSIGHT\n{"score":87,"recommendation":"apply",'
        '"reason":"Core requirements match.","industry_business":"Fintech",'
        '"role_focus":"Backend","summary":"Build payments.",'
        '"top_strength":"Go","top_gap":"Payments"}'
    )

    class ResumeService:
        def active_resume_text(self, *, user_id: str) -> str:
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


def test_current_task_service_returns_document_and_merges_prior_result() -> None:
    agent = JobMatchAgent(
        client=fake_client("@@SECTION cover_letter\nDear Hiring Manager"),
        model="m",
    )
    agent._cv_text = "Go / 5 years"
    service = TaskService(
        agents={AgentName.JOB_MATCH: agent},
        repository=None,
        resume_service=None,
        default_model="m",
    )
    request = task_request(
        "write_cover_letter",
        selectedText="",
        priorResult="@@SECTION conclusion\nMatch 82.",
    )

    response = service.execute(
        request,
        user_id=None,
        agent_override=AgentName.JOB_MATCH,
    )

    assert response.document.text.startswith("@@SECTION conclusion")
    assert [section.id for section in response.document.sections] == [
        "conclusion",
        "cover_letter",
    ]


def test_unsupported_current_task_action_is_rejected() -> None:
    agent = JobMatchAgent()
    agent._cv_text = "Go"

    with pytest.raises(ValueError, match="Unsupported current task action"):
        agent.build_prompt(task_request("mock_interview"))
