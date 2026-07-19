import json
import os
import re
from pathlib import Path

from pypdf import PdfReader

from app.agents.base import (
    AgentContext,
    AgentExecution,
    OpenAIChatAgent,
    format_workspace_context,
    language_directive,
)
from app.modules.task.schema import (
    Action,
    ActionId,
    AgentName,
    DetailsInsightCard,
    DocumentContent,
    Insight,
    InsightItem,
    PageContext,
    QuickInsightRequest,
    ScoreInsightCard,
    Section,
    TaskRequest,
    TextInsightCard,
    WorkspaceRequest,
)
from app.render import render_markdown

SYSTEM_PROMPT = (
    "你是 Agent Bridge 的求职助手,同时是一位资深 HR / 招聘官。用户会给你两部分材料:"
    "(1) 他的简历,(2) 他当前正在浏览的招聘职位页面。\n"
    "你深知招聘方怎么看一份申请:HR 平均只花 6-8 秒扫一份简历,先判断是否『对口』;"
    "最能抓住眼球的是——与职位描述(JD)高度吻合的关键词、可量化的成果、清晰的职业轨迹;"
    "简历通常先过 ATS 关键词筛选再到人眼。请始终用招聘方的视角帮用户审视自己、产出内容,"
    "让 HR 在几秒内就被吸引。\n"
    "注意区分两种任务:『结论』『技能匹配』是帮用户认清真实胜算的诊断,必须诚实、克制、"
    "不给安慰分;『求职信』『简历更新建议』才是帮用户把已有材料包装得更吸引 HR。两者不要相互污染。\n"
    "严格按要求输出若干区块:每个区块以单独一行 `@@SECTION <id>` 开头,"
    "紧接着是该区块的 Markdown 内容。只输出被要求的区块,顺序一致,"
    "不要在 `@@SECTION` 行加任何别的文字,不要输出额外说明。"
    "只依据所给材料,不要编造简历或职位中没有的信息。\n"
    "重要:如果『当前招聘职位页面』明显不是招聘职位页面(例如是聊天记录、文档、"
    "搜索结果、代码或其它与招聘无关的内容),绝对不要编造职位或匹配结果。"
    "此时【只】输出一个 `@@SECTION conclusion`,内容为:这不是招聘职位页面,"
    "无法进行简历匹配,请打开完整的招聘职位页面或选中职位描述后再试;并且不要输出任何其它区块。"
)

QUICK_INSIGHT_INSTRUCTION = '''
只输出 `@@INSIGHT` 一行和紧随其后的一个 JSON 对象，不输出 Markdown 或额外文字。
JSON 必须包含这些字段：
{"score":0,"recommendation":"apply","reason":"一句核心判断","industry_business":"行业与业务","role_focus":"岗位核心","summary":"1-2句职责摘要","top_strength":"最重要的一项优势","top_gap":"最重要的一项差距"}
recommendation 只能是 strong_apply、apply、cautious、skip。score 必须是 0-100 整数。
评分继续遵守核心要求缺失不高于 65、多项部分满足不高于 75、基本命中 80+ 的克制标尺。
'''.strip()
QUICK_INSIGHT_SYSTEM_PROMPT = (
    "你是 Agent Bridge 的求职助手,同时是一位资深 HR / 招聘官。"
    "只依据所给简历和职位材料,不得编造信息。\n"
    + QUICK_INSIGHT_INSTRUCTION
)

WORKSPACE_SYSTEM_PROMPT = (
    "You are Agent Bridge's senior recruiting and job-application assistant. "
    "Follow the selected Workspace action and answer only from the supplied job, resume, "
    "draft, and conversation context. Never invent experience or qualifications. "
    "Return clean Markdown without @@SECTION transport markers."
)

WORKSPACE_ACTION_INSTRUCTIONS = {
    ActionId.ANALYZE: (
        "Produce a complete job analysis grounded in the job description and resume. "
        "Cover the business and role, hard requirements, strengths, gaps, realistic fit, "
        "application risks, and concrete next steps."
    ),
    ActionId.TAILOR_RESUME: (
        "Produce the complete ATS-friendly resume tailored to this job, not suggestions or "
        "a partial patch. Preserve factual accuracy, prioritize relevant keywords and "
        "quantified achievements, and revise the supplied current draft when present."
    ),
    ActionId.WRITE_COVER_LETTER: (
        "Produce the complete ready-to-send cover letter tailored to this job. Keep every "
        "claim grounded in the resume and revise the supplied current draft when present."
    ),
    ActionId.ASK_MORE: (
        "Answer the user's open question directly, using the resume, job description, shared "
        "conversation, and current page as context."
    ),
}

WORKSPACE_DOCUMENT_KINDS = {
    ActionId.ANALYZE: "analysis",
    ActionId.TAILOR_RESUME: "resume",
    ActionId.WRITE_COVER_LETTER: "cover_letter",
    ActionId.ASK_MORE: "",
}

WORKSPACE_ACTION_TITLES = {
    "en": {
        ActionId.ANALYZE: "Analyze",
        ActionId.TAILOR_RESUME: "Tailor Resume",
        ActionId.WRITE_COVER_LETTER: "Generate Cover Letter",
        ActionId.ASK_MORE: "Ask More",
    },
    "zh": {
        ActionId.ANALYZE: "分析岗位",
        ActionId.TAILOR_RESUME: "定制简历",
        ActionId.WRITE_COVER_LETTER: "撰写求职信",
        ActionId.ASK_MORE: "继续提问",
    },
}

WORKSPACE_DOCUMENT_TITLES = {
    "en": {
        ActionId.ANALYZE: "Job Analysis",
        ActionId.TAILOR_RESUME: "Tailored Resume",
        ActionId.WRITE_COVER_LETTER: "Cover Letter",
        ActionId.ASK_MORE: "",
    },
    "zh": {
        ActionId.ANALYZE: "岗位分析",
        ActionId.TAILOR_RESUME: "定制简历",
        ActionId.WRITE_COVER_LETTER: "求职信",
        ActionId.ASK_MORE: "",
    },
}

DOCUMENT_EDIT_ACTIONS = {
    ActionId.TAILOR_RESUME,
    ActionId.WRITE_COVER_LETTER,
}

JOB_WORKSPACE_ACTION_IDS = (
    ActionId.ANALYZE,
    ActionId.TAILOR_RESUME,
    ActionId.WRITE_COVER_LETTER,
    ActionId.ASK_MORE,
)


def _insight_title(lang: str) -> str:
    """Return the localized Quick Insight title."""

    return "Job Match" if lang == "en" else "岗位匹配"

# 各区块的展示标题(按语言切换)、是否提供"复制"按钮、是否允许折叠。
# collapsible=False 的区块前端始终展开;True 的超长时自动折叠。
SECTION_META = {
    "conclusion": {"zh": "结论", "en": "Summary", "copyable": False, "collapsible": False},
    "overview": {"zh": "业务介绍", "en": "Business Overview", "copyable": False, "collapsible": False},
    "skills": {"zh": "技能匹配", "en": "Skills Match", "copyable": False, "collapsible": True},
    "cover_letter": {"zh": "求职信", "en": "Cover Letter", "copyable": True, "collapsible": True},
    "resume_tips": {"zh": "简历更新建议", "en": "Resume Update Tips", "copyable": True, "collapsible": True},
}

# 区块生成指令(id -> instruction)。展示标题/复制/折叠见 SECTION_META。
SECTION_INSTRUCTIONS = {
    "conclusion": (
        "用一句话同时给出两点:① 该职位所属的行业 + 具体业务;"
        "② 简历与该职位的匹配评分(0-100)。"
        "评分务必克制、真实,不给安慰分,并与后面『技能匹配』里的 ✅/⚠️/❌ 自洽。"
        "先识别该岗位『反复强调、决定能否胜任的硬性核心要求』,"
        "按核心要求命中情况打分:核心要求出现 ❌ 缺失 → 不应高于 65;"
        "多项核心要求仅 ⚠️ 部分满足 → 不应高于 75;核心要求基本命中、仅边角缺口 → 80+;"
        "几乎全部命中 → 90+。通用基础技能再突出也不能补偿核心要求的缺失;"
        "若经验年限明显超出岗位要求,也要在这句里点明可能被视为『资历过高』。只要这一句,精炼直给。"
    ),
    "overview": (
        "用 2-4 句话客观介绍:这家公司/产品到底在做什么业务、面向什么市场,"
        "以及这个岗位主要负责什么。目的是让用户快速判断自己是否对这个业务方向感兴趣。"
        "只描述,不评价匹配度。"
    ),
    "skills": (
        "站在招聘方筛选的角度,列出该职位要求的关键技能/经验,逐项标注简历是否命中:"
        "✅ 具备 / ⚠️ 部分 / ❌ 缺失,各附一句简要依据。"
        "⚠️/❌ 正是 HR 会质疑的点,可顺带点一句如何弥补或扬长避短。用 Markdown 表格或列表。"
    ),
    "cover_letter": (
        "用 HR/招聘官的阅读习惯,写一封可直接发送的求职信,分段排版、便于 6 秒扫读:"
        "① 称呼:一行问候(JD 里有公司名就带上,如『尊敬的 XX 招聘团队』);"
        "② 开头钩子:1-2 句直接点出你最匹配该岗位的量化核心价值,不要客套寒暄;"
        "③ 主体:2-3 个最相关的匹配点,各成一小段,每点必须对应 JD 的一项具体要求并带量化"
        "(数字/规模/结果);严禁『有着深刻理解和丰富经验』这类无事实支撑的空话;"
        "④ 结尾:一句自信、具体的沟通邀约(不要泛泛的抱负);"
        "⑤ 落款:换行『此致』,再换行写 [你的名字] 占位。"
        "全文约 200-300 字,段落之间空行分隔。只输出信件本身,不要任何解释或 Markdown 标题。"
    ),
    "resume_tips": (
        "以 HR『6 秒扫一眼』的视角,用可扫读的分点列表给出让这份简历瞬间显得『对口』的具体修改建议:"
        "① 哪些与 JD 吻合的关键词/技能要前置、加粗或放到简历靠前位置(兼顾 ATS 关键词筛选);"
        "② 哪些经历应改写成可量化成果——给出『改前 → 改后』的示例措辞;"
        "③ 哪些与该岗位无关的内容可弱化或删减。每条都简短、可直接照做。"
    ),
}

# 右键默认只跑匹配分析三块;求职信/建议按需生成。
DEFAULT_SECTIONS = ["conclusion", "overview", "skills"]
# 喂给模型的顺序:skills 在 conclusion 之前,使评分被技能匹配锚定。
GENERATION_ORDER = ["overview", "skills", "conclusion", "cover_letter", "resume_tips"]
# 回前端的展示顺序:conclusion 置顶(前端把它当 lede)。
DISPLAY_ORDER = ["conclusion", "overview", "skills", "cover_letter", "resume_tips"]

ACTION_SECTIONS = {
    "summary": ["conclusion", "overview"],
    "deep_analysis": DEFAULT_SECTIONS,
    "write_cover_letter": ["cover_letter", "resume_tips"],
    # Deprecated extension action id, accepted only while /tasks is supported.
    "generate_cover_letter": ["cover_letter", "resume_tips"],
}

# 简历路径,相对网关运行目录(gateway/)。可用环境变量覆盖。
DEFAULT_CV_PATH = os.environ.get("AGENT_BRIDGE_CV_PATH", "data/cv/cv.pdf")
MAX_CV_CHARS = 15000
# 选中的职位描述少于该字符数就直接失败。真实 JD 通常上千字(历史数据里真实匹配的选中
# 文本都 >2000 字);而误匹配(把产品文档/聊天记录等当岗位)的选中文本都很短(≤约 100 字)。
# 阈值取 1000 留足余量:过短即判定 JD 资料不足,让用户去选完整职位描述,而不是让模型硬凑。
# 只看选中文本,不用页面正文兜底(页面正文恰是长的非招聘页误匹配的来源)。
MIN_JOB_CONTENT_CHARS = 1000

_SECTION_RE = re.compile(r"^@@SECTION\s+(\w+)\s*$", re.MULTILINE)


class JobMatchAgent(OpenAIChatAgent):
    """Stateless job Agent for match insights and Workspace application tasks."""

    name = AgentName.JOB_MATCH
    requires_resume = True
    system_prompt = SYSTEM_PROMPT

    def __init__(self, *args, cv_path: str | Path | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cv_path = Path(cv_path or DEFAULT_CV_PATH)
        self._cv_text: str | None = None

    def cv_text(self) -> str:
        # Read + cache once; raises a clear error if the CV is missing/empty.
        if self._cv_text is None:
            self._cv_text = self._read_cv()
        return self._cv_text

    def _resolve_cv_text(self, override: str | None) -> str:
        """云端多租户:用调用方注入的当前用户简历文本;
        无注入(开源单用户)时回退到本地 AGENT_BRIDGE_CV_PATH。"""
        if override and override.strip():
            return override
        return self.cv_text()

    def _read_cv(self) -> str:
        if not self.cv_path.exists():
            raise FileNotFoundError(
                f"未找到简历文件: {self.cv_path} 。请把简历放到该路径,"
                f"或用环境变量 AGENT_BRIDGE_CV_PATH 指定。"
            )
        reader = PdfReader(str(self.cv_path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if not text:
            raise ValueError(
                f"简历 {self.cv_path} 中没有可提取的文本(可能是扫描版 PDF)。"
            )
        return text

    def _validate_request(self, task: PageContext) -> None:
        """没有选中足够的职位描述就直接失败,避免模型凭空编造职位/匹配。

        只看 selected_text,不再用 page_text 兜底:历史数据显示真实匹配的选中文本
        都远超阈值,而误匹配(在聊天/空白页右键)选中文本都极短——页面正文恰是误匹配
        的来源。续跑(有 prior_result)时跳过该检查。由 TaskService 在调用模型前预检
        (抛 ValueError -> API 返回 400,且不耗 token)。
        """
        if isinstance(task, TaskRequest) and task.prior_result and task.prior_result.strip():
            return
        if len(task.selected_text.strip()) < MIN_JOB_CONTENT_CHARS:
            raise ValueError(
                f"选中的职位描述太少(不足 {MIN_JOB_CONTENT_CHARS} 字),JD 资料不足以可靠匹配。"
                "请在招聘页面选中完整的职位描述(JD)后再试。"
            )

    def validate(self, ctx: AgentContext) -> None:
        """Validate job evidence and any Workspace Action before model execution."""

        self._validate_request(ctx.request)
        if isinstance(ctx.request, WorkspaceRequest):
            self._workspace_action(ctx.request)

    def actions(self, ctx: AgentContext) -> list[Action]:
        """Declare the ordered job Workspace modes for this request language."""

        title_lang = "en" if ctx.request.lang == "en" else "zh"
        titles = WORKSPACE_ACTION_TITLES[title_lang]
        return [
            Action(id=action_id, title=titles[action_id])
            for action_id in JOB_WORKSPACE_ACTION_IDS
        ]

    def _workspace_action(self, task: WorkspaceRequest) -> ActionId:
        """Return a supported typed Action or reject mutated/invalid input early."""

        try:
            action_id = ActionId(task.action_id)
        except ValueError as exc:
            raise ValueError(f"Unsupported workspace action: {task.action_id}") from exc
        if action_id not in WORKSPACE_ACTION_INSTRUCTIONS:
            raise ValueError(f"Unsupported workspace action: {task.action_id}")
        return action_id

    def _workspace_page_context(self, task: WorkspaceRequest) -> str:
        """Render the current job page without treating it as trusted instructions."""

        return "\n".join(
            [
                f"Title: {task.title}",
                f"URL: {task.url}",
                "Job description (selected text):",
                task.selected_text.strip(),
                "Image clues (alt/caption/aria-label):",
                task.image_text.strip() or "(none)",
            ]
        )

    def _build_workspace_prompt(self, task: WorkspaceRequest, cv: str) -> str:
        """Build one action-specific prompt from request-scoped Workspace state."""

        action_id = self._workspace_action(task)
        lines = [
            "# Workspace action",
            WORKSPACE_ACTION_INSTRUCTIONS[action_id],
            "",
            "# Resume",
            cv,
        ]
        if action_id in DOCUMENT_EDIT_ACTIONS and task.current_document is not None:
            lines.extend(
                [
                    "",
                    "# Current document draft",
                    f"Kind: {task.current_document.kind}",
                    f"Title: {task.current_document.title}",
                    task.current_document.text,
                ]
            )
        lines.extend(
            [
                "",
                format_workspace_context(
                    task,
                    page_context=self._workspace_page_context(task),
                ),
            ]
        )
        return "\n".join(lines)

    def _requested_sections(self, task: TaskRequest) -> list[str]:
        sections = ACTION_SECTIONS.get(task.action_id)
        if sections is None:
            raise ValueError(f"Unsupported current task action: {task.action_id}")
        return sections

    def _section_request_lines(self, sections: list[str]) -> list[str]:
        lines = ["请按顺序输出以下区块:"]
        for sid in GENERATION_ORDER:
            if sid in sections:
                lines.append(f"@@SECTION {sid} — {SECTION_INSTRUCTIONS[sid]}")
        return lines

    def build_prompt(self, task: PageContext, cv_text: str | None = None) -> str:
        """Build Quick Insight, Workspace, or unchanged legacy task prompts."""

        # 兜底:任何路径构造 prompt 前都先校验,确保模型不会在稀疏内容上瞎编。
        self._validate_request(task)
        cv = self._resolve_cv_text(cv_text)[:MAX_CV_CHARS]
        if isinstance(task, QuickInsightRequest):
            return "\n".join(
                [
                    QUICK_INSIGHT_INSTRUCTION,
                    "",
                    "# 我的简历",
                    cv,
                    "",
                    "# 当前招聘职位(用户在页面上选中的内容)",
                    f"标题: {task.title}",
                    f"链接: {task.url}",
                    "职位描述(选中文字):",
                    task.selected_text.strip(),
                    "图片线索(alt/说明):",
                    task.image_text.strip() or "(无)",
                ]
            )
        if isinstance(task, WorkspaceRequest):
            return self._build_workspace_prompt(task, cv)
        if not isinstance(task, TaskRequest):
            raise TypeError("Current task execution requires TaskRequest")
        section_lines = self._section_request_lines(self._requested_sections(task))
        if task.prior_result and task.prior_result.strip():
            # 续跑:基于阶段一分析 + 简历生成,不带页面正文。
            # 去掉 @@SECTION 标记行,避免模型把阶段一内容当新输出区块。
            prior_text = _SECTION_RE.sub("", task.prior_result).strip()
            return "\n".join(
                [
                    *section_lines,
                    "",
                    "# 我的简历",
                    cv,
                    "",
                    "# 前序匹配分析(基于它来写,不要重复输出它)",
                    prior_text,
                ]
            )
        return "\n".join(
            [
                *section_lines,
                "",
                "# 我的简历",
                cv,
                "",
                "# 当前招聘职位(用户在页面上选中的内容)",
                "标题:",
                task.title,
                "链接:",
                task.url,
                "职位描述(选中文字):",
                task.selected_text.strip(),
                "图片线索(alt/说明):",
                task.image_text.strip() or "(无)",
            ]
        )

    def _complete_request(
        self, task: PageContext, cv_text: str | None = None
    ) -> tuple[str, str, str]:
        """Execute the correct prompt protocol for a typed job request."""

        if isinstance(task, QuickInsightRequest):
            system_prompt = QUICK_INSIGHT_SYSTEM_PROMPT
        elif isinstance(task, WorkspaceRequest):
            system_prompt = WORKSPACE_SYSTEM_PROMPT
        else:
            system_prompt = self.system_prompt
        system = system_prompt + "\n\n" + language_directive(task.lang)
        prompt = self.build_prompt(task, cv_text=cv_text)
        output, model = self.complete_prompt(system=system, prompt=prompt)
        if isinstance(task, TaskRequest) and task.prior_result and task.prior_result.strip():
            # 把阶段二输出拼到阶段一分析之后,使返回值即「合并全量文本」;
            # service/build_sections 因此无需感知 prior_result。
            output = task.prior_result.rstrip() + "\n\n" + output
        return output, prompt, model

    def build_sections(self, result: str, lang: str) -> list[Section]:
        """Split the model output on `@@SECTION <id>` markers into renderable blocks."""
        title_lang = "en" if lang == "en" else "zh"
        sections: list[Section] = []

        matches = list(_SECTION_RE.finditer(result))
        if not matches:
            # 模型没按格式输出:整体作为一个区块,保证不丢内容。
            body = result.strip()
            if body:
                sections.append(
                    Section(id="result", title="", html=render_markdown(body))
                )
            return sections

        for i, m in enumerate(matches):
            sid = m.group(1)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(result)
            body = result[start:end].strip()
            meta = SECTION_META.get(sid, {})
            sections.append(
                Section(
                    id=sid,
                    title=meta.get(title_lang, sid),
                    html=render_markdown(body),
                    copyable=bool(meta.get("copyable", False)),
                    collapsible=bool(meta.get("collapsible", True)),
                )
            )
        # 生成顺序(skills 先于 conclusion)≠ 展示顺序;按 DISPLAY_ORDER 重排,未知 id 稳定排末尾。
        order = {sid: i for i, sid in enumerate(DISPLAY_ORDER)}
        sections.sort(key=lambda s: order.get(s.id, len(DISPLAY_ORDER)))
        return sections

    def build_insight(self, result: str, lang: str) -> Insight:
        marker, sep, payload = result.partition("@@INSIGHT")
        if marker.strip() or not sep:
            raise ValueError("Quick Insight response is missing @@INSIGHT")
        try:
            data = json.loads(payload.strip())
            if not isinstance(data, dict) or type(data.get("score")) is not int:
                raise TypeError("score must be an integer")
            return Insight(
                title=_insight_title(lang),
                cards=[
                    ScoreInsightCard(
                        id="decision",
                        title="Decision" if lang == "en" else "申请建议",
                        score=data["score"],
                        recommendation=data["recommendation"],
                        reason=data["reason"],
                    ),
                    DetailsInsightCard(
                        id="job_overview",
                        title="Job Overview" if lang == "en" else "岗位概览",
                        items=[
                            InsightItem(label="industry_business", value=data["industry_business"]),
                            InsightItem(label="role_focus", value=data["role_focus"]),
                        ],
                        summary=data["summary"],
                    ),
                    TextInsightCard(
                        id="top_strength",
                        title="Top Strength" if lang == "en" else "最大优势",
                        body_html=render_markdown(data["top_strength"]),
                    ),
                    TextInsightCard(
                        id="top_gap",
                        title="Top Gap" if lang == "en" else "最大差距",
                        body_html=render_markdown(data["top_gap"]),
                    ),
                ],
            )
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("Quick Insight response is invalid") from exc

    def insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        """Generate a typed match insight; Actions are declared separately."""

        result, prompt, model = self._complete_request(ctx.request, ctx.resume_text)
        return AgentExecution(
            content=self.build_insight(result, ctx.request.lang),
            raw_result=result,
            prompt=prompt,
            model=model,
        )

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        """Execute an action-specific Workspace task or the legacy section flow."""

        if not isinstance(ctx.request, TaskRequest | WorkspaceRequest):
            raise TypeError("Task execution requires TaskRequest or WorkspaceRequest")
        if isinstance(ctx.request, WorkspaceRequest):
            action_id = self._workspace_action(ctx.request)
            result, prompt, model = self._complete_request(ctx.request, ctx.resume_text)
            html = render_markdown(result)
            title_lang = "en" if ctx.request.lang == "en" else "zh"
            return AgentExecution(
                content=DocumentContent(
                    kind=WORKSPACE_DOCUMENT_KINDS[action_id],
                    title=WORKSPACE_DOCUMENT_TITLES[title_lang][action_id],
                    text=result,
                    html=html,
                    sections=[Section(id="result", title="", html=html)],
                ),
                raw_result=result,
                prompt=prompt,
                model=model,
            )
        result, prompt, model = self._complete_request(ctx.request, ctx.resume_text)
        sections = self.build_sections(result, ctx.request.lang)
        html = "".join(
            (f"<h3>{section.title}</h3>{section.html}" if section.title else section.html)
            for section in sections
        )
        return AgentExecution(
            content=DocumentContent(text=result, html=html, sections=sections),
            raw_result=result,
            prompt=prompt,
            model=model,
        )
