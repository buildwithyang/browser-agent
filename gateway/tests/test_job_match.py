from types import SimpleNamespace

import pytest

from app.agents.job_match import JobMatchAgent
from app.modules.task.schema import TaskCreate


def make_task() -> TaskCreate:
    return TaskCreate(
        url="https://example.com/jobs/9",
        title="Senior Go Engineer",
        page_text=(
            "We need Go, Kubernetes, distributed systems, and 5 years of backend "
            "experience for our Dubai fintech payments platform."
        ),
    )


def test_prompt_includes_cv_and_job():
    agent = JobMatchAgent()
    agent._cv_text = "我会 Go 和 Kubernetes,有 5 年后端经验。"  # bypass PDF read

    prompt = agent.build_prompt(make_task())

    assert "Go 和 Kubernetes" in prompt
    assert "Senior Go Engineer" in prompt
    assert "We need Go, Kubernetes" in prompt
    # 一次请求要求全部区块(含业务介绍)
    assert "@@SECTION conclusion" in prompt
    assert "@@SECTION overview" in prompt
    assert "@@SECTION skills" in prompt
    assert "@@SECTION cover_letter" in prompt
    assert "@@SECTION resume_tips" in prompt


def test_build_sections_parses_markers_and_flags():
    agent = JobMatchAgent()
    raw = (
        "@@SECTION conclusion\n金融科技支付行业,匹配度 88。\n"
        "@@SECTION overview\n这家公司做跨境支付。\n"
        "@@SECTION skills\n- Go ✅\n- K8s ⚠️\n"
        "@@SECTION cover_letter\nDear Hiring Manager, ...\n"
        "@@SECTION resume_tips\n- 量化你的成果\n"
    )

    sections = agent.build_sections(raw, "zh")

    ids = [s.id for s in sections]
    assert ids == ["conclusion", "overview", "skills", "cover_letter", "resume_tips"]
    # 业务介绍排在技能匹配之前,且始终展开(不可折叠)
    assert ids.index("overview") < ids.index("skills")
    overview = next(s for s in sections if s.id == "overview")
    assert overview.title == "业务介绍"
    assert overview.collapsible is False
    cover = next(s for s in sections if s.id == "cover_letter")
    assert cover.title == "求职信"
    assert cover.copyable is True
    assert cover.collapsible is True
    assert "Dear Hiring Manager" in cover.html
    # 结论区块不可复制
    assert sections[0].copyable is False


def test_build_sections_fallback_when_no_markers():
    agent = JobMatchAgent()
    sections = agent.build_sections("模型忘了加标记,直接输出了一段。", "zh")
    assert len(sections) == 1
    assert sections[0].id == "result"


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


def test_validate_rejects_sparse_content():
    agent = JobMatchAgent()
    sparse = TaskCreate(url="https://x.com/j", title="Job", page_text="Go")
    with pytest.raises(ValueError):
        agent.validate(sparse)


def test_validate_passes_when_selection_has_enough():
    agent = JobMatchAgent()
    # 页面正文为空,但选中了足够长的职位描述 -> 通过。
    sel = "We need a senior Go engineer with Kubernetes and distributed systems experience."
    agent.validate(TaskCreate(url="https://x.com/j", title="Job", selectedText=sel))


def test_build_prompt_rejects_sparse_content():
    agent = JobMatchAgent()
    agent._cv_text = "Go / 5y backend"  # 即便有简历,内容太少也不该构造 prompt
    with pytest.raises(ValueError):
        agent.build_prompt(TaskCreate(url="https://x.com/j", title="Job", page_text="hi"))
