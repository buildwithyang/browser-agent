import pytest
from pydantic import ValidationError

from app.modules.task.schema import (
    Action,
    AgentName,
    JobOverview,
    QuickInsight,
    TaskCreate,
    TaskResponse,
)


def test_taskcreate_defaults_have_no_sections_or_prior_result():
    t = TaskCreate(url="https://x.com/j")
    assert t.sections is None
    assert t.prior_result is None


def test_taskcreate_accepts_sections_and_prior_result_camel_alias():
    t = TaskCreate(
        url="https://x.com/j",
        sections=["cover_letter", "resume_tips"],
        priorResult="@@SECTION conclusion\n匹配度 60。",
    )
    assert t.sections == ["cover_letter", "resume_tips"]
    assert t.prior_result.startswith("@@SECTION conclusion")


def test_taskresponse_actions_default_empty():
    r = TaskResponse(request=TaskCreate(url="https://x.com/j"))
    assert r.actions == []


def test_action_model_shape():
    a = Action(id="generate_cover_letter", label="✍️ 生成求职信",
               sections=["cover_letter", "resume_tips"])
    assert a.id == "generate_cover_letter"
    assert a.sections == ["cover_letter", "resume_tips"]


def test_browser_agent_is_valid_input_name():
    assert (
        TaskCreate(url="https://example.com", agent="browser_agent").agent
        is AgentName.BROWSER_AGENT
    )


def test_taskcreate_parses_agent_name_enum_and_serializes_existing_value():
    task = TaskCreate(url="https://example.com", agent="browser_agent")

    assert task.agent is AgentName.BROWSER_AGENT
    assert task.model_dump(mode="json")["agent"] == "browser_agent"


def test_job_quick_insight_shape():
    insight = QuickInsight(
        type="job_match",
        title="Job Match",
        score=87,
        recommendation="apply",
        reason="Core requirements match; direct payments experience is missing.",
        job_overview=JobOverview(
            industry_business="Fintech · B2B payments",
            role_focus="Transaction-platform backend",
            summary="Build reliable payment services.",
        ),
        top_strength="Go and distributed systems",
        top_gap="Direct payments experience",
    )
    assert insight.score == 87
    assert insight.job_overview.role_focus == "Transaction-platform backend"


def test_quick_insight_rejects_score_outside_range():
    with pytest.raises(ValidationError):
        QuickInsight(type="job_match", title="Job Match", score=101)


def test_summary_quick_insight_has_no_job_score():
    insight = QuickInsight(
        type="summary",
        title="Page Summary",
        summary_html="<p>Key point.</p>",
    )
    assert insight.score is None
    assert insight.job_overview is None


def test_action_supports_current_task_metadata():
    action = Action(
        id="ask_more",
        label="Ask more",
        task_type="ask_more",
        enabled=False,
        sections=[],
    )
    assert action.task_type == "ask_more"
    assert action.enabled is False
