import re

from app.agents.base import (
    AgentContext,
    AgentExecution,
    format_workspace_context,
    language_directive,
)
from app.agents.job_match.quick_insight import (
    MAX_CV_CHARS,
    CompletePrompt,
    ResolveResumeText,
    validate_job_request,
)
from app.modules.task.schema import (
    ActionId,
    DocumentContent,
    PageContext,
    Section,
    TaskRequest,
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

SECTION_META = {
    "conclusion": {
        "zh": "结论",
        "en": "Summary",
        "copyable": False,
        "collapsible": False,
    },
    "overview": {
        "zh": "业务介绍",
        "en": "Business Overview",
        "copyable": False,
        "collapsible": False,
    },
    "skills": {
        "zh": "技能匹配",
        "en": "Skills Match",
        "copyable": False,
        "collapsible": True,
    },
    "cover_letter": {
        "zh": "求职信",
        "en": "Cover Letter",
        "copyable": True,
        "collapsible": True,
    },
    "resume_tips": {
        "zh": "简历更新建议",
        "en": "Resume Update Tips",
        "copyable": True,
        "collapsible": True,
    },
}

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

DEFAULT_SECTIONS = ["conclusion", "overview", "skills"]
GENERATION_ORDER = [
    "overview",
    "skills",
    "conclusion",
    "cover_letter",
    "resume_tips",
]
DISPLAY_ORDER = [
    "conclusion",
    "overview",
    "skills",
    "cover_letter",
    "resume_tips",
]
ACTION_SECTIONS = {
    "summary": ["conclusion", "overview"],
    "deep_analysis": DEFAULT_SECTIONS,
    "write_cover_letter": ["cover_letter", "resume_tips"],
    "generate_cover_letter": ["cover_letter", "resume_tips"],
}

_SECTION_RE = re.compile(r"^@@SECTION\s+(\w+)\s*$", re.MULTILINE)


class LegacyJobMatchExecutor:
    """Temporary adapter preserving v1 Workspace and `/tasks` document execution."""

    def __init__(
        self,
        *,
        complete_prompt: CompletePrompt,
        resolve_resume_text: ResolveResumeText,
    ) -> None:
        """Inject shared model execution and request-scoped resume resolution."""

        self._complete_prompt = complete_prompt
        self._resolve_resume_text = resolve_resume_text

    def validate_workspace_action(self, request: WorkspaceRequest) -> ActionId:
        """Return a supported typed v1 Action or reject mutated input."""

        try:
            action_id = ActionId(request.action_id)
        except ValueError as exc:
            raise ValueError(f"Unsupported workspace action: {request.action_id}") from exc
        if action_id not in WORKSPACE_ACTION_INSTRUCTIONS:
            raise ValueError(f"Unsupported workspace action: {request.action_id}")
        return action_id

    def _workspace_page_context(self, request: WorkspaceRequest) -> str:
        """Render the current job page without treating it as trusted instructions."""

        return "\n".join(
            [
                f"Title: {request.title}",
                f"URL: {request.url}",
                "Job description (selected text):",
                request.selected_text.strip(),
                "Image clues (alt/caption/aria-label):",
                request.image_text.strip() or "(none)",
            ]
        )

    def _build_workspace_prompt(self, request: WorkspaceRequest, resume: str) -> str:
        """Build one action-specific v1 Workspace prompt."""

        action_id = self.validate_workspace_action(request)
        lines = [
            "# Workspace action",
            WORKSPACE_ACTION_INSTRUCTIONS[action_id],
            "",
            "# Resume",
            resume,
        ]
        if action_id in DOCUMENT_EDIT_ACTIONS and request.current_document is not None:
            lines.extend(
                [
                    "",
                    "# Current document draft",
                    f"Kind: {request.current_document.kind}",
                    f"Title: {request.current_document.title}",
                    request.current_document.text,
                ]
            )
        lines.extend(
            [
                "",
                format_workspace_context(
                    request,
                    page_context=self._workspace_page_context(request),
                ),
            ]
        )
        return "\n".join(lines)

    def _requested_sections(self, request: TaskRequest) -> list[str]:
        """Resolve the legacy section set for one extension Action id."""

        sections = ACTION_SECTIONS.get(request.action_id)
        if sections is None:
            raise ValueError(f"Unsupported current task action: {request.action_id}")
        return sections

    def _section_request_lines(self, sections: list[str]) -> list[str]:
        """Format requested legacy sections in model generation order."""

        lines = ["请按顺序输出以下区块:"]
        for section_id in GENERATION_ORDER:
            if section_id in sections:
                lines.append(
                    f"@@SECTION {section_id} — {SECTION_INSTRUCTIONS[section_id]}"
                )
        return lines

    def build_prompt(
        self,
        request: PageContext,
        resume_text: str | None,
    ) -> str:
        """Build one unchanged legacy Task or v1 Workspace document prompt."""

        validate_job_request(request)
        resume = self._resolve_resume_text(resume_text)[:MAX_CV_CHARS]
        if isinstance(request, WorkspaceRequest):
            return self._build_workspace_prompt(request, resume)
        if not isinstance(request, TaskRequest):
            raise TypeError("Current task execution requires TaskRequest")
        section_lines = self._section_request_lines(self._requested_sections(request))
        if request.prior_result and request.prior_result.strip():
            prior_text = _SECTION_RE.sub("", request.prior_result).strip()
            return "\n".join(
                [
                    *section_lines,
                    "",
                    "# 我的简历",
                    resume,
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
                resume,
                "",
                "# 当前招聘职位(用户在页面上选中的内容)",
                "标题:",
                request.title,
                "链接:",
                request.url,
                "职位描述(选中文字):",
                request.selected_text.strip(),
                "图片线索(alt/说明):",
                request.image_text.strip() or "(无)",
            ]
        )

    def _complete_request(
        self,
        request: PageContext,
        resume_text: str | None,
    ) -> tuple[str, str, str]:
        """Execute the unchanged model protocol for one legacy document request."""

        system_prompt = (
            WORKSPACE_SYSTEM_PROMPT
            if isinstance(request, WorkspaceRequest)
            else SYSTEM_PROMPT
        )
        system = system_prompt + "\n\n" + language_directive(request.lang)
        prompt = self.build_prompt(request, resume_text)
        output, model = self._complete_prompt(system=system, prompt=prompt)
        if isinstance(request, TaskRequest) and request.prior_result and request.prior_result.strip():
            output = request.prior_result.rstrip() + "\n\n" + output
        return output, prompt, model

    def build_sections(self, result: str, lang: str) -> list[Section]:
        """Split legacy `@@SECTION` output into ordered renderable blocks."""

        title_lang = "en" if lang == "en" else "zh"
        sections: list[Section] = []
        matches = list(_SECTION_RE.finditer(result))
        if not matches:
            body = result.strip()
            if body:
                sections.append(Section(id="result", title="", html=render_markdown(body)))
            return sections

        for index, match in enumerate(matches):
            section_id = match.group(1)
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(result)
            body = result[start:end].strip()
            meta = SECTION_META.get(section_id, {})
            sections.append(
                Section(
                    id=section_id,
                    title=meta.get(title_lang, section_id),
                    html=render_markdown(body),
                    copyable=bool(meta.get("copyable", False)),
                    collapsible=bool(meta.get("collapsible", True)),
                )
            )
        order = {section_id: index for index, section_id in enumerate(DISPLAY_ORDER)}
        sections.sort(key=lambda section: order.get(section.id, len(DISPLAY_ORDER)))
        return sections

    def execute(self, context: AgentContext) -> AgentExecution[DocumentContent]:
        """Return the temporary v1 document response using context resume text."""

        request = context.request
        if not isinstance(request, TaskRequest | WorkspaceRequest):
            raise TypeError("Task execution requires TaskRequest or WorkspaceRequest")
        if isinstance(request, WorkspaceRequest):
            action_id = self.validate_workspace_action(request)
            result, prompt, model = self._complete_request(request, context.resume_text)
            html = render_markdown(result)
            title_lang = "en" if request.lang == "en" else "zh"
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

        result, prompt, model = self._complete_request(request, context.resume_text)
        sections = self.build_sections(result, request.lang)
        html = "".join(
            (
                f"<h3>{section.title}</h3>{section.html}"
                if section.title
                else section.html
            )
            for section in sections
        )
        return AgentExecution(
            content=DocumentContent(text=result, html=html, sections=sections),
            raw_result=result,
            prompt=prompt,
            model=model,
        )
