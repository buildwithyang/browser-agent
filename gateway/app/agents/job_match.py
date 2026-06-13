import os
import re
from pathlib import Path

from pypdf import PdfReader

from app.agents.base import OpenAIChatAgent
from app.models import Section, TaskCreate
from app.render import render_markdown

SYSTEM_PROMPT = (
    "你是 Agent Bridge 的求职助手。用户会给你两部分材料:(1) 他的简历,"
    "(2) 他当前正在浏览的招聘职位页面。\n"
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
        "例:『金融科技支付行业的后端岗位,与你的背景匹配度 85』。只要这一句,精炼直给。",
    ),
    (
        "overview",
        "用 2-4 句话客观介绍:这家公司/产品到底在做什么业务、面向什么市场,"
        "以及这个岗位主要负责什么。目的是让用户快速判断自己是否对这个业务方向感兴趣。"
        "只描述,不评价匹配度。",
    ),
    (
        "skills",
        "列出该职位要求的关键技能/经验,逐项标注简历是否具备:"
        "✅ 具备 / ⚠️ 部分 / ❌ 缺失,各附一句简要依据。用 Markdown 表格或列表。",
    ),
    (
        "cover_letter",
        "写一封可直接发送的求职信:简洁、针对该职位、突出最相关的匹配点。"
        "只要信件正文,不要额外解释或标题。",
    ),
    (
        "resume_tips",
        "针对这个职位,给出简历的具体更新建议:应强化或补充哪些经历与技能、"
        "措辞如何调整、有哪些可量化成果。条理清晰、可执行。",
    ),
]

# 简历路径,相对网关运行目录(gateway/)。可用环境变量覆盖。
DEFAULT_CV_PATH = os.environ.get("AGENT_BRIDGE_CV_PATH", "data/cv/cv.pdf")
MAX_CV_CHARS = 15000

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

    def build_prompt(self, task: TaskCreate) -> str:
        section_lines = ["请按顺序输出以下区块:"]
        for sid, instruction in SECTION_SPECS:
            section_lines.append(f"@@SECTION {sid} — {instruction}")

        return "\n".join(
            [
                *section_lines,
                "",
                "# 我的简历",
                self.cv_text()[:MAX_CV_CHARS],
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
