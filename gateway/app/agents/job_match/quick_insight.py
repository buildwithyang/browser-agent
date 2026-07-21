import json
from collections.abc import Callable
from types import MappingProxyType

from app.agents.base import AgentContext, AgentExecution, language_directive
from app.modules.task.schema import (
    DetailsInsightCard,
    Insight,
    InsightItem,
    PageContext,
    QuickInsightRequest,
    PromptShortcutId,
    ScoreInsightCard,
    TextInsightCard,
)
from app.render import render_markdown

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

PROMPT_SHORTCUT_CATALOGUES = MappingProxyType({
    "en": (
        (
            PromptShortcutId.ANALYZE,
            "Analyze",
            'Analyze what this role actually values. Use a Markdown table with exactly two columns, "JD Requirement" and "Match", to compare each material requirement against my resume. After the table, summarize my strongest matches, core gaps, and whether it is worth applying, with a clear recommendation and reasons.',
        ),
        (
            PromptShortcutId.TAILOR_RESUME,
            "Tailor Resume",
            "Compare the current job description with my resume. First identify the experiences worth emphasizing and the sections you plan to change. Do not generate a new resume yet; wait for my confirmation.",
        ),
        (
            PromptShortcutId.WRITE_COVER_LETTER,
            "Generate Cover Letter",
            "Using the current job description and my resume, write a concise, specific cover letter without exaggeration. Emphasize only the experience most relevant to the role.",
        ),
        (PromptShortcutId.ASK_MORE, "Ask More", ""),
    ),
    "zh": (
        (
            PromptShortcutId.ANALYZE,
            "分析岗位",
            "请分析这个岗位真正看重的能力，并以 Markdown 表格逐项对比“JD 要求”和“匹配情况”。表格后总结我的匹配优势、核心差距，以及是否值得申请，并给出明确结论和理由。",
        ),
        (
            PromptShortcutId.TAILOR_RESUME,
            "定制简历",
            "请结合当前 JD 和我的简历，先指出最值得强化的经历及你计划修改的部分。暂时不要生成新简历，等我确认后再生成。",
        ),
        (
            PromptShortcutId.WRITE_COVER_LETTER,
            "撰写求职信",
            "请结合当前 JD 和我的简历，生成一封简洁、具体、不过度夸张的求职信，重点突出与岗位最相关的经历。",
        ),
        (PromptShortcutId.ASK_MORE, "继续提问", ""),
    ),
})
"""Immutable ordered localized Prompt Shortcut definitions."""

MAX_CV_CHARS = 15000
# Real selected job descriptions are historically much longer than sparse accidental
# selections, so routing and validation share this conservative evidence threshold.
MIN_JOB_CONTENT_CHARS = 1000

CompletePrompt = Callable[..., tuple[str, str]]
ResolveResumeText = Callable[[str | None], str]


def insight_title(lang: str) -> str:
    """Return the localized Quick Insight title."""

    return "Job Match" if lang == "en" else "岗位匹配"


def validate_job_request(request: PageContext) -> None:
    """Reject sparse job evidence before any Quick Insight model call."""

    if len(request.selected_text.strip()) < MIN_JOB_CONTENT_CHARS:
        raise ValueError(
            f"选中的职位描述太少(不足 {MIN_JOB_CONTENT_CHARS} 字),JD 资料不足以可靠匹配。"
            "请在招聘页面选中完整的职位描述(JD)后再试。"
        )


class JobQuickInsightAgent:
    """Stateless Quick Insight component used by the job-match facade."""

    def __init__(
        self,
        *,
        complete_prompt: CompletePrompt,
        resolve_resume_text: ResolveResumeText,
    ) -> None:
        """Inject model execution and per-request resume resolution dependencies."""

        self._complete_prompt = complete_prompt
        self._resolve_resume_text = resolve_resume_text

    def build_prompt(self, request: QuickInsightRequest, resume_text: str | None) -> str:
        """Build the strict job Quick Insight prompt from request-scoped input."""

        validate_job_request(request)
        resume = self._resolve_resume_text(resume_text)[:MAX_CV_CHARS]
        return "\n".join(
            [
                QUICK_INSIGHT_INSTRUCTION,
                "",
                "# 我的简历",
                resume,
                "",
                "# 当前招聘职位(用户在页面上选中的内容)",
                f"标题: {request.title}",
                f"链接: {request.url}",
                "职位描述(选中文字):",
                request.selected_text.strip(),
                "图片线索(alt/说明):",
                request.image_text.strip() or "(无)",
            ]
        )

    def build_insight(self, result: str, lang: str) -> Insight:
        """Parse one strict model payload into decision-first typed cards."""

        marker, separator, payload = result.partition("@@INSIGHT")
        if marker.strip() or not separator:
            raise ValueError("Quick Insight response is missing @@INSIGHT")
        try:
            data = json.loads(payload.strip())
            if not isinstance(data, dict) or type(data.get("score")) is not int:
                raise TypeError("score must be an integer")
            return Insight(
                title=insight_title(lang),
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
                            InsightItem(
                                label="industry_business",
                                value=data["industry_business"],
                            ),
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

    def execute(self, context: AgentContext) -> AgentExecution[Insight]:
        """Generate one typed Quick Insight without retaining request state."""

        request = context.request
        if not isinstance(request, QuickInsightRequest):
            raise TypeError("Quick Insight execution requires QuickInsightRequest")
        prompt = self.build_prompt(request, context.resume_text)
        system = QUICK_INSIGHT_SYSTEM_PROMPT + "\n\n" + language_directive(request.lang)
        result, model = self._complete_prompt(system=system, prompt=prompt)
        return AgentExecution(
            content=self.build_insight(result, request.lang),
            raw_result=result,
            prompt=prompt,
            model=model,
        )
