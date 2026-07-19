from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.job_match import MIN_JOB_CONTENT_CHARS, JobMatchAgent
from app.modules.task.schema import (
    AgentName,
    DetailsInsightCard,
    QuickInsightRequest,
    ScoreInsightCard,
    TaskRequest,
    TextInsightCard,
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
