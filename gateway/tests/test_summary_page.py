from types import SimpleNamespace

from app.agents.summary_page import SummaryPageAgent
from app.modules.task.schema import TaskCreate


def full_page_task() -> TaskCreate:
    return TaskCreate(
        intent="Analyze this job for resume fit.",
        url="https://example.com/jobs/123",
        title="Senior Golang Engineer",
        selected_text="",  # no selection -> summarize the whole page
        page_text="We need Go, Kubernetes, and backend experience.",
        image_text="Org chart diagram · Office photo",
    )


def selection_task() -> TaskCreate:
    return TaskCreate(
        url="https://example.com/jobs/123",
        title="Senior Golang Engineer",
        selected_text="Dubai remote role, visa sponsored",
        page_text="We need Go, Kubernetes, and backend experience.",
        image_text="Org chart diagram",
    )


def test_full_page_prompt_contains_page_and_image_clues():
    prompt = SummaryPageAgent().build_prompt(full_page_task())

    assert "Analyze this job for resume fit." in prompt
    assert "Senior Golang Engineer" in prompt
    assert "We need Go, Kubernetes" in prompt
    assert "Org chart diagram" in prompt  # image clues reach the model


def test_selection_prompt_focuses_on_selection():
    prompt = SummaryPageAgent().build_prompt(selection_task())

    assert "Dubai remote role, visa sponsored" in prompt
    assert "selected" in prompt.lower()  # instruction to focus on the selection
    # In selection mode we do NOT dump the rest of the page.
    assert "We need Go, Kubernetes" not in prompt
    assert "Org chart diagram" not in prompt


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
    result = agent.run(full_page_task())

    assert result == "Here are the next steps."
    assert captured["model"] == "gpt-4o-mini"
    # The page context reaches the model via the user message (index 1; the
    # system prompt is index 0).
    user_text = captured["messages"][1]["content"]
    assert "Senior Golang Engineer" in user_text
