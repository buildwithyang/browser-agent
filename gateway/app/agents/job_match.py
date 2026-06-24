import os
import re
from pathlib import Path

from pypdf import PdfReader

from app.agents.base import OpenAIChatAgent, language_directive
from app.modules.task.schema import Section, TaskCreate
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
    "只依据所给材料,不要编造简历或职位中没有的信息。"
)

# 各区块的展示标题(按语言切换)、是否提供"复制"按钮、是否允许折叠。
# collapsible=False 的区块前端始终展开;True 的超长时自动折叠。
SECTION_META = {
    "conclusion": {"zh": "结论", "en": "Summary", "copyable": False, "collapsible": False},
    "overview": {"zh": "业务介绍", "en": "Business Overview", "copyable": False, "collapsible": False},
    "skills": {"zh": "技能匹配", "en": "Skills Match", "copyable": False, "collapsible": True},
    "cover_letter": {"zh": "求职信", "en": "Cover Letter", "copyable": True, "collapsible": True},
    "resume_tips": {"zh": "简历更新建议", "en": "Resume Update Tips", "copyable": True, "collapsible": True},
}

# 一次请求输出全部区块,按此顺序。
SECTION_SPECS = [
    (
        "conclusion",
        "用一句话【同时】给出两点:① 该职位所属的行业 + 具体业务;"
        "② 简历与该职位的匹配评分(0-100)。两者必须都出现在这一句里。"
        "评分务必克制、真实,不给安慰分。先在心里对照该岗位的『硬性核心要求』"
        "(即这个岗位之所以存在的根本目的,如本例的 AI/LLM/检索、知识图谱)再打分,"
        "并使分数与后面『技能匹配』里的 ✅/⚠️/❌ 自洽。评分锚点:"
        "核心要求出现 ❌ 缺失时不应高于 65;有多项 ⚠️/❌ 时不应高于 75;"
        "核心要求基本命中、仅边角有缺口才给 80+;几乎完美匹配才给 90+。"
        "通用基础技能(如某门后端语言)再强也无法补偿核心领域的缺失;"
        "若经验年限远超岗位要求(如 12 年 vs 要求 1-3 年),也要在这句里点明可能被视为『资历过高』。"
        "例:『面向 AI Agent 的记忆与上下文平台,但核心的 AI/检索经验缺失,与你的背景匹配度约 60』。"
        "只要这一句,精炼直给。",
    ),
    (
        "overview",
        "用 2-4 句话客观介绍:这家公司/产品到底在做什么业务、面向什么市场,"
        "以及这个岗位主要负责什么。目的是让用户快速判断自己是否对这个业务方向感兴趣。"
        "只描述,不评价匹配度。",
    ),
    (
        "skills",
        "站在招聘方筛选的角度,列出该职位要求的关键技能/经验,逐项标注简历是否命中:"
        "✅ 具备 / ⚠️ 部分 / ❌ 缺失,各附一句简要依据。"
        "⚠️/❌ 正是 HR 会质疑的点,可顺带点一句如何弥补或扬长避短。用 Markdown 表格或列表。",
    ),
    (
        "cover_letter",
        "用 HR/招聘官的阅读习惯,写一封可直接发送、前两句就抓住对方的求职信:"
        "① 开头用一句有冲击力的『钩子』直接点出你最匹配该岗位的核心价值(尽量带量化成果),不要客套寒暄;"
        "② 主体用 2-3 个最相关的匹配点,尽量量化(数字、规模、结果)并呼应 JD 关键词;"
        "③ 结尾给出清晰、自信的下一步意向。全文精炼(约 200-250 字),只要信件正文,不要额外解释或标题。",
    ),
    (
        "resume_tips",
        "以 HR『6 秒扫一眼』的视角,给出让这份简历瞬间显得『对口』的具体修改建议:"
        "① 哪些与 JD 吻合的关键词/技能要前置、加粗或放到简历靠前位置(兼顾 ATS 关键词筛选);"
        "② 哪些经历应改写成可量化成果——给出『改前 → 改后』的示例措辞;"
        "③ 哪些与该岗位无关的内容可弱化或删减。条理清晰、可直接照做。",
    ),
]

# 简历路径,相对网关运行目录(gateway/)。可用环境变量覆盖。
DEFAULT_CV_PATH = os.environ.get("AGENT_BRIDGE_CV_PATH", "data/cv/cv.pdf")
MAX_CV_CHARS = 15000
# 职位内容(页面正文或选中文字,取较长者)少于该字符数时直接失败,
# 避免在几乎没内容的页面上让模型凭空编造职位/匹配结果。
MIN_JOB_CONTENT_CHARS = 80

_SECTION_RE = re.compile(r"^@@SECTION\s+(\w+)\s*$", re.MULTILINE)


class JobMatchAgent(OpenAIChatAgent):
    name = "job_match"
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

    def validate(self, task: TaskCreate) -> None:
        """内容太少就直接失败,避免模型凭空编造职位/匹配。

        由 TaskService 在调用模型前预检(抛 ValueError -> API 返回 400,且不耗 token)。
        """
        job_chars = max(len(task.page_text.strip()), len(task.selected_text.strip()))
        if job_chars < MIN_JOB_CONTENT_CHARS:
            raise ValueError(
                "这个页面没抓到足够的职位内容,无法进行简历匹配。"
                "请打开完整的招聘职位页面,或选中职位描述文字后再试。"
            )

    def build_prompt(self, task: TaskCreate, cv_text: str | None = None) -> str:
        # 兜底:任何路径构造 prompt 前都先校验,确保模型不会在稀疏内容上瞎编。
        self.validate(task)
        section_lines = ["请按顺序输出以下区块:"]
        for sid, instruction in SECTION_SPECS:
            section_lines.append(f"@@SECTION {sid} — {instruction}")

        return "\n".join(
            [
                *section_lines,
                "",
                "# 我的简历",
                self._resolve_cv_text(cv_text)[:MAX_CV_CHARS],
                "",
                "# 当前招聘职位页面",
                "标题:",
                task.title,
                "链接:",
                task.url,
                "选中文本:",
                task.selected_text.strip() or "(无)",
                "页面内容:",
                task.page_text.strip() or "(无)",
                "图片线索(alt/说明):",
                task.image_text.strip() or "(无)",
            ]
        )

    def run(self, task: TaskCreate, cv_text: str | None = None) -> str:
        system = self.system_prompt + "\n\n" + language_directive(task.lang)
        prompt = self.build_prompt(task, cv_text=cv_text)
        return self.complete(system, prompt, tier=self._router.pick(len(prompt)))

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
        return sections
