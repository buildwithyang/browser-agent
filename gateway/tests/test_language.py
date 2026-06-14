from types import SimpleNamespace

from app.agents.summary_page import SummaryPageAgent
from app.modules.task.schema import TaskCreate


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
    task = TaskCreate(url="https://x.com", title="t", page_text="body", lang=lang)
    SummaryPageAgent(client=fake_client, model="m").run(task)
    return captured["messages"][0]["content"]


def test_lang_zh_directive():
    assert "简体中文" in run_with_lang("zh")


def test_lang_en_directive():
    assert "Respond entirely in English" in run_with_lang("en")


def test_lang_auto_directive():
    assert "same language as the page" in run_with_lang("auto")


def test_default_lang_is_auto():
    task = TaskCreate(url="https://x.com", title="t")
    assert task.lang == "auto"
