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


def test_default_prompt_has_analysis_only():
    agent = JobMatchAgent()
    agent._cv_text = "我会 Go 和 Kubernetes,有 5 年后端经验。"

    prompt = agent.build_prompt(make_task())

    assert "Go 和 Kubernetes" in prompt
    assert "Senior Go Engineer" in prompt
    # 默认右键只跑匹配分析三块
    assert "@@SECTION conclusion" in prompt
    assert "@@SECTION overview" in prompt
    assert "@@SECTION skills" in prompt
    # 求职信/建议默认不生成
    assert "@@SECTION cover_letter" not in prompt
    assert "@@SECTION resume_tips" not in prompt


def test_generation_order_puts_skills_before_conclusion():
    agent = JobMatchAgent()
    agent._cv_text = "Go / 5y backend"
    prompt = agent.build_prompt(make_task())
    assert prompt.index("@@SECTION skills") < prompt.index("@@SECTION conclusion")


def test_build_sections_resorts_to_display_order():
    agent = JobMatchAgent()
    # 模型按生成顺序输出(skills 在 conclusion 前),展示应重排成 conclusion 置顶
    raw = (
        "@@SECTION skills\n- Go ✅\n"
        "@@SECTION conclusion\n匹配度 60。\n"
        "@@SECTION overview\n做支付。\n"
    )
    ids = [s.id for s in agent.build_sections(raw, "zh")]
    assert ids == ["conclusion", "overview", "skills"]


def test_conclusion_rubric_is_generic():
    from app.agents.job_match import SECTION_INSTRUCTIONS
    rubric = SECTION_INSTRUCTIONS["conclusion"]
    assert "AI/LLM" not in rubric          # 不再写死具体技能
    assert "65" in rubric                  # 保留通用评分锚点
    assert "资历过高" in rubric


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


def make_continue_task() -> TaskCreate:
    return TaskCreate(
        url="https://example.com/jobs/9",
        title="Senior Go Engineer",
        sections=["cover_letter", "resume_tips"],
        priorResult="@@SECTION conclusion\n金融科技,匹配度 82。\n@@SECTION skills\n- Go ✅\n",
    )


def test_continuation_prompt_uses_prior_result_not_page_text():
    agent = JobMatchAgent()
    agent._cv_text = "Go / Kubernetes / 5y backend"
    prompt = agent.build_prompt(make_continue_task())
    assert "@@SECTION cover_letter" in prompt
    assert "@@SECTION resume_tips" in prompt
    assert "@@SECTION conclusion" not in prompt        # 续跑不重生成分析
    assert "金融科技,匹配度 82" in prompt              # 带入阶段一分析
    assert "Go / Kubernetes" in prompt                 # 带入简历


def test_validate_allows_empty_page_when_prior_result_present():
    agent = JobMatchAgent()
    agent._cv_text = "Go"
    # page_text 为空但有 prior_result -> 不抛
    agent.validate(make_continue_task())


def test_run_continuation_prepends_prior_result():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="@@SECTION cover_letter\nDear Hiring Manager\n"))]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    agent = JobMatchAgent(client=fake_client, model="gpt-4o-mini")
    agent._cv_text = "Go / 5y"

    result = agent.run(make_continue_task())

    assert result.startswith("@@SECTION conclusion")   # 前序分析在前
    assert "@@SECTION cover_letter" in result          # 模型输出在后
    # 合并文本切块得到全量区块、按展示顺序
    ids = [s.id for s in agent.build_sections(result, "zh")]
    assert ids[0] == "conclusion"
    assert "cover_letter" in ids
