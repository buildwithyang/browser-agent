import os
from pathlib import Path

from pypdf import PdfReader

from app.agents.base import OpenAIChatAgent
from app.models import TaskCreate

SYSTEM_PROMPT = (
    "你是 Agent Bridge 的求职匹配助手。用户会给你两部分材料:(1) 他的简历,"
    "(2) 他当前正在浏览的招聘职位页面。请用中文、用 Markdown 分析该职位与简历的匹配程度:\n"
    "- 先用一句话给出总体结论,并给出一个匹配评分(0-100),单独成段。\n"
    "- **匹配优势**:列出简历中契合职位要求的点。\n"
    "- **欠缺/风险**:列出职位要求但简历未体现或较弱的点。\n"
    "- **建议**:针对这个职位,投递或面试前可以补充、强调的内容。\n"
    "只依据所给材料,不要编造简历或职位中没有的信息。"
)

# 简历路径,相对网关运行目录(gateway/)。可用环境变量覆盖。
DEFAULT_CV_PATH = os.environ.get("AGENT_BRIDGE_CV_PATH", "data/cv/cv.pdf")
MAX_CV_CHARS = 15000


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
        return "\n".join(
            [
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
            ]
        )
