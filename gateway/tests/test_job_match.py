from types import SimpleNamespace

import pytest

from app.agents.job_match import MIN_JOB_CONTENT_CHARS, JobMatchAgent
from app.modules.task.schema import AgentName, TaskCreate


# 真实 JD 通常上千字;门控要求选中内容 >= MIN_JOB_CONTENT_CHARS(1000)字。
LONG_JD = (
    "Senior Backend Engineer — we are hiring. Responsibilities: design and operate "
    "high-throughput distributed systems; build and maintain gRPC and REST APIs; "
    "own reliability, on-call rotations, and performance tuning for a global, "
    "consumer-facing platform serving millions of daily active users; collaborate "
    "across teams on architecture and capacity planning. Requirements: 5+ years of "
    "professional backend engineering; expert in Go; solid Kubernetes, message "
    "queues, databases, caching, and observability; proven track record scaling "
    "production services under heavy load. Nice to have: payments, IoT, or "
    "real-time messaging experience. We offer competitive compensation, remote "
    "flexibility, and an engineering culture focused on ownership and impact. "
) * 2
assert len(LONG_JD) >= MIN_JOB_CONTENT_CHARS  # 守护:该 fixture 必须越过门控


def make_task() -> TaskCreate:
    # JD 来自用户选中的文字(page_text 不再参与匹配)。
    return TaskCreate(
        url="https://example.com/jobs/9",
        title="Senior Go Engineer",
        selected_text=LONG_JD,
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


def test_validate_rejects_long_page_without_selection():
    agent = JobMatchAgent()
    # 像在 ChatGPT/任意网页右键:页面正文很长,但没选中职位描述 -> 必须拒绝,
    # 不能再凭页面正文瞎编职位(这正是历史上的误匹配根因)。
    junk = "Skip to content Chat history ChatGPT New chat Search chats " * 30
    task = TaskCreate(url="https://chatgpt.com/c/x", title="ChatGPT", page_text=junk)
    assert len(junk) > MIN_JOB_CONTENT_CHARS  # 页面正文远超阈值
    with pytest.raises(ValueError):
        agent.validate(task)


def test_validate_passes_when_selection_has_enough():
    agent = JobMatchAgent()
    # 选中了足够长的完整职位描述 -> 通过。
    agent.validate(TaskCreate(url="https://x.com/j", title="Job", selectedText=LONG_JD))


def test_validate_rejects_short_non_job_selection():
    agent = JobMatchAgent()
    # 这正是误匹配的根因:选中了一段短产品文档/技术介绍(非 JD),长度不足 1000 字 -> 拒绝。
    product_doc = (
        "通过部署全球边缘计算节点与智能路由技术,系统现已支持全球范围内的极速就近接入。"
        "您无需再根据服务器物理位置手动切换或配置不同地域的节点,所有网络环境下的请求均统一使用我们的全局主端点。"
    )
    assert 80 <= len(product_doc) < MIN_JOB_CONTENT_CHARS  # 越过旧的 80 门控,但仍属"资料太少"
    with pytest.raises(ValueError):
        agent.validate(TaskCreate(url="https://doczh.x.ai/d", title="Base URL", selectedText=product_doc))


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


def test_actions_offers_cover_letter_on_stage_one():
    agent = JobMatchAgent()
    acts = agent.actions(make_task(), "zh")
    assert len(acts) == 1
    assert acts[0].id == "generate_cover_letter"
    assert acts[0].sections == ["cover_letter", "resume_tips"]
    assert "求职信" in acts[0].label


def test_actions_label_english():
    agent = JobMatchAgent()
    acts = agent.actions(make_task(), "en")
    assert len(acts) == 1
    assert "cover letter" in acts[0].label.lower()


def test_actions_empty_for_quick_insight():
    agent = JobMatchAgent()
    task = make_task().model_copy(
        update={"agent": AgentName.JOB_MATCH, "intent": "quick_insight"}
    )

    assert agent.actions(task, "en") == []


def test_actions_empty_on_continuation():
    agent = JobMatchAgent()
    assert agent.actions(make_continue_task(), "zh") == []


def test_actions_empty_when_cover_letter_already_requested():
    agent = JobMatchAgent()
    task = TaskCreate(
        url="https://x.com/j",
        title="Job",
        sections=["cover_letter", "skills"],
    )
    assert agent.actions(task, "zh") == []


def test_prompt_omits_page_text():
    agent = JobMatchAgent()
    agent._cv_text = "Go / 5y backend"
    task = TaskCreate(
        url="https://x.com/j",
        title="Senior Go Engineer",
        selected_text=LONG_JD,
        page_text="UNRELATED PAGE NOISE should never reach the model",
    )
    prompt = agent.build_prompt(task)
    assert "Senior Backend Engineer" in prompt        # 选中的 JD 进入 prompt
    assert "UNRELATED PAGE NOISE" not in prompt        # 页面正文不再发给模型


def test_system_prompt_guards_non_job_pages():
    from app.agents.job_match import SYSTEM_PROMPT
    # 模型端兼防:选中的是非招聘内容时,提示词要求拒绝而不是编造匹配。
    assert "不是招聘职位页面" in SYSTEM_PROMPT


def test_build_insight_parses_typed_job_decision():
    agent = JobMatchAgent()
    raw = '''@@INSIGHT
{"score":87,"recommendation":"apply","reason":"核心要求基本命中。","industry_business":"金融科技 · B2B 支付","role_focus":"交易平台后端","summary":"负责高可用支付服务。","top_strength":"Go 与分布式系统","top_gap":"缺少直接支付经验"}'''
    insight = agent.build_insight(raw, "zh")
    assert insight.type == "job_match"
    assert insight.score == 87
    assert insight.recommendation == "apply"
    assert insight.job_overview.industry_business == "金融科技 · B2B 支付"
    assert insight.top_strength == "Go 与分布式系统"


def test_build_insight_rejects_invalid_json():
    agent = JobMatchAgent()
    with pytest.raises(ValueError, match="Quick Insight"):
        agent.build_insight("@@INSIGHT\nnot json", "zh")


@pytest.mark.parametrize("payload", ["[]", "null", "1"])
def test_build_insight_rejects_non_object_json(payload):
    agent = JobMatchAgent()
    with pytest.raises(ValueError, match="Quick Insight"):
        agent.build_insight(f"@@INSIGHT\n{payload}", "en")


@pytest.mark.parametrize("score", ['"87"', "87.0", "true"])
def test_build_insight_rejects_non_integer_score(score):
    agent = JobMatchAgent()
    raw = f'''@@INSIGHT
{{"score":{score},"recommendation":"apply","reason":"match","industry_business":"fintech","role_focus":"backend","summary":"payments","top_strength":"Go","top_gap":"payments"}}'''
    with pytest.raises(ValueError, match="Quick Insight"):
        agent.build_insight(raw, "en")


@pytest.mark.parametrize(
    "raw",
    [
        '@@INSIGHT\n{"score":87,"recommendation":"apply"}',
        '@@INSIGHT\n{"score":87,"recommendation":"maybe","reason":"match",'
        '"industry_business":"fintech","role_focus":"backend",'
        '"summary":"payments","top_strength":"Go","top_gap":"payments"}',
        '@@INSIGHT\n{"score":101,"recommendation":"apply","reason":"match",'
        '"industry_business":"fintech","role_focus":"backend",'
        '"summary":"payments","top_strength":"Go","top_gap":"payments"}',
        'preface\n@@INSIGHT\n{"score":87}',
        '@@INSIGHT\n{"score":87,"recommendation":"apply","reason":"match",'
        '"industry_business":"fintech","role_focus":"backend",'
        '"summary":"payments","top_strength":"Go","top_gap":"payments"}\nextra',
    ],
    ids=[
        "missing_fields",
        "invalid_recommendation",
        "score_out_of_range",
        "prefix_text",
        "trailing_text",
    ],
)
def test_build_insight_rejects_non_contract_output(raw):
    agent = JobMatchAgent()

    with pytest.raises(ValueError, match="Quick Insight"):
        agent.build_insight(raw, "en")


def test_quick_insight_prompt_requests_only_decision_fields():
    agent = JobMatchAgent()
    agent._cv_text = "Go / Kubernetes / 5 years"
    task = make_task().model_copy(
        update={"agent": AgentName.JOB_MATCH, "intent": "quick_insight"}
    )
    prompt = agent.build_prompt(task)
    assert "@@INSIGHT" in prompt
    assert '"score"' in prompt
    assert "cover_letter" not in prompt


def test_run_quick_insight_uses_json_system_contract():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="@@INSIGHT\n{}"))]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    agent = JobMatchAgent(client=fake_client, model="gpt-4o-mini")
    agent._cv_text = "Go / Kubernetes / 5 years"
    task = make_task().model_copy(
        update={"agent": AgentName.JOB_MATCH, "intent": "quick_insight"}
    )

    agent.run(task)

    system = captured["messages"][0]["content"]
    assert "@@INSIGHT" in system
    assert "@@SECTION" not in system
