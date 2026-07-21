from types import SimpleNamespace

from app.agents.base import AgentContext, WorkspaceAgentContext
from app.agents.job_match.planner import OutputMode
from app.agents.job_match.specialists.analysis import JobAnalysisAgent
from app.agents.summary_page import SummaryPageAgent
from app.modules.task.schema import QuickInsightRequest, WorkspaceRequest


def run_with_lang(lang: str) -> str:
    """Run the agent with a fake client and return the system message sent."""
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    task = QuickInsightRequest(url="https://x.com", title="t", page_text="body", lang=lang)
    SummaryPageAgent(client=fake_client, model="m").quick_insight(
        AgentContext(request=task)
    )
    return captured["messages"][0]["content"]


def test_lang_zh_directive():
    assert "简体中文" in run_with_lang("zh")


def test_lang_en_directive():
    assert "Respond entirely in English" in run_with_lang("en")


def test_lang_auto_directive():
    assert "same language as the page" in run_with_lang("auto")


def test_default_lang_is_auto():
    task = QuickInsightRequest(url="https://x.com", title="t")
    assert task.lang == "auto"


def test_workspace_uses_language_directive() -> None:
    """Apply output-language constraints to the explicit Workspace path."""

    captured = {}

    def fake_create(**kwargs):
        """Capture the explicit Workspace chat system prompt."""

        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    request = WorkspaceRequest(
        url="https://x.com",
        resourceUrl="https://x.com",
        operationId="00000000-0000-0000-0000-000000000001",
        title="t",
        pageText="body",
        lang="zh",
        histories=[],
        artifacts={"cv": None, "cover_letter": None},
        message="What changed?",
    )

    SummaryPageAgent(client=client, model="m").handle_chat(WorkspaceAgentContext(request=request))

    assert "简体中文" in captured["messages"][0]["content"]


def test_job_analysis_english_contract_uses_exact_two_column_header() -> None:
    """Keep the English job comparison header aligned with the Shortcut promise."""

    agent = JobAnalysisAgent(open_prompt_stream=lambda **_kwargs: None)  # type: ignore[arg-type]
    system = agent.build_system_prompt("en", OutputMode.REPLY)

    assert "| JD Requirement | Match |" in system
    assert "| --- | --- |" in system
