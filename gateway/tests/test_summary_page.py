from types import SimpleNamespace

from app.agents.summary_page import SummaryPageAgent
from app.models import TaskCreate


def make_task() -> TaskCreate:
    return TaskCreate(
        intent="Analyze this job for resume fit.",
        url="https://example.com/jobs/123",
        title="Senior Golang Engineer",
        selected_text="Dubai remote role",
        page_text="We need Go, Kubernetes, and backend experience.",
    )


def test_prompt_contains_browser_context():
    prompt = SummaryPageAgent().build_prompt(make_task())

    assert "Analyze this job for resume fit." in prompt
    assert "https://example.com/jobs/123" in prompt
    assert "Senior Golang Engineer" in prompt
    assert "Dubai remote role" in prompt
    assert "We need Go, Kubernetes" in prompt


def test_run_returns_model_text_and_passes_model():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Here are the next steps.")
                )
            ]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    agent = SummaryPageAgent(client=fake_client, model="gpt-4o-mini")
    result = agent.run(make_task())

    assert result == "Here are the next steps."
    assert captured["model"] == "gpt-4o-mini"
    # The page context reaches the model via the user message (index 1; the
    # system prompt is index 0).
    user_text = captured["messages"][1]["content"]
    assert "Senior Golang Engineer" in user_text
