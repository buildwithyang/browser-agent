from types import SimpleNamespace

import pytest

from app.agents.job_match import JobMatchAgent
from app.models import TaskCreate


def make_task() -> TaskCreate:
    return TaskCreate(
        url="https://example.com/jobs/9",
        title="Senior Go Engineer",
        page_text="We need Go, Kubernetes, 5y backend.",
    )


def test_prompt_includes_cv_and_job():
    agent = JobMatchAgent()
    agent._cv_text = "我会 Go 和 Kubernetes,有 5 年后端经验。"  # bypass PDF read

    prompt = agent.build_prompt(make_task())

    assert "Go 和 Kubernetes" in prompt
    assert "Senior Go Engineer" in prompt
    assert "We need Go, Kubernetes" in prompt


def test_run_passes_model_and_cv():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="匹配度 80。"))]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    agent = JobMatchAgent(client=fake_client, model="gpt-4o-mini")
    agent._cv_text = "Go / Kubernetes / 5y backend"

    result = agent.run(make_task())

    assert result == "匹配度 80。"
    assert captured["model"] == "gpt-4o-mini"
    assert "Go / Kubernetes" in captured["messages"][1]["content"]


def test_missing_cv_raises(tmp_path):
    agent = JobMatchAgent(cv_path=tmp_path / "nope.pdf")
    with pytest.raises(FileNotFoundError):
        agent.build_prompt(make_task())
