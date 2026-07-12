from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, Literal, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "successful"
    data: T


# 内置 OpenAI-backed agents。"claude-code"/"codex" 为未来外部适配预留，暂未实现。
AgentName = Literal[
    "browser_agent", "summary_page", "job_match", "claude-code", "codex", "openclaw"
]
Recommendation = Literal["strong_apply", "apply", "cautious", "skip"]

# /tasks 输入封顶：防止匿名/恶意调用塞超大正文烧平台 LLM 钱。
PAGE_TEXT_MAX_CHARS = 200_000
SELECTED_TEXT_MAX_CHARS = 100_000
IMAGE_TEXT_MAX_CHARS = 50_000


class TaskCreate(BaseModel):
    """浏览器扩展提交的任务(agent 的输入契约）。

    扩展发送扁平的 camelCase 负载(``{url, title, selectedText, pageText}``),
    这里用别名接收，同时对网关其余部分暴露 snake_case 属性。
    """

    model_config = ConfigDict(populate_by_name=True)

    url: str
    title: str = ""
    selected_text: str = Field("", alias="selectedText", max_length=SELECTED_TEXT_MAX_CHARS)
    page_text: str = Field("", alias="pageText", max_length=PAGE_TEXT_MAX_CHARS)
    # 图片文字线索(alt / caption / aria-label),纯文本,不含图片本身。
    image_text: str = Field("", alias="imageText", max_length=IMAGE_TEXT_MAX_CHARS)
    # 按需分阶段:job_match 用。省略=默认分析集;非空=只生成被点名的区块。
    sections: list[str] | None = None
    # 续跑时回传的阶段一 result 文本(求职信/建议基于它生成,无需重传页面正文)。
    prior_result: str | None = Field(default=None, alias="priorResult", max_length=50_000)
    intent: str = "Summarize this page."
    agent: AgentName = "summary_page"
    # 输出语言:"zh"/"en" 强制;"auto" 跟随页面语言。扩展通常已把用户偏好解析为 zh/en。
    lang: Literal["auto", "zh", "en"] = "auto"


class Section(BaseModel):
    """agent 结果中的一个可渲染区块（折叠面板 UI 用）。

    是否折叠由前端按长度决定，网关只标注是否值得提供「复制」按钮。
    """

    id: str
    title: str
    html: str  # sanitized HTML (rendered from the section's Markdown)
    copyable: bool = False
    # False = 前端始终展开(如业务介绍);True = 内容超长时前端自动折叠。
    collapsible: bool = True


class JobOverview(BaseModel):
    industry_business: str
    role_focus: str
    summary: str


class QuickInsight(BaseModel):
    type: Literal["job_match", "summary"]
    title: str
    summary_html: str = ""
    score: int | None = Field(default=None, ge=0, le=100)
    recommendation: Recommendation | None = None
    reason: str = ""
    job_overview: JobOverview | None = None
    top_strength: str = ""
    top_gap: str = ""


class Action(BaseModel):
    """结果上可触发的后续动作。后端声明,前端照单渲染按钮(未来新动作纯后端添加)。"""

    id: str
    label: str
    sections: list[str] = Field(default_factory=list)
    task_type: str = ""
    enabled: bool = True


class TaskResponse(BaseModel):
    """返回给扩展的完整结果。不含 prompt（含简历/页面正文，无需回传客户端）。"""

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["created", "completed", "failed"] = "created"
    request: TaskCreate
    input_chars: int = 0  # 发给模型的 prompt 长度（仅指标）
    model: str = ""  # 实际路由到的模型
    result: str = ""
    result_html: str = ""
    sections: list[Section] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    insight: QuickInsight | None = None
    error: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class TaskRecordData(BaseModel):
    """落库的任务记录领域对象。

    默认 metrics-only。下面的明细字段仅在 TASK_DEBUG_STORE 开启时由 service 填充，
    用于对比不同模型效果；含隐私，不会回传给前端(recent 列表不读取它们)。
    """

    id: str
    user_id: str | None = None
    agent: str
    lang: str = "auto"
    model: str = ""
    status: str = "completed"
    input_chars: int = 0
    result_chars: int = 0
    duration_ms: int | None = None
    error: str = ""
    created_at: datetime
    # debug 明细(默认 None)
    url: str | None = None
    title: str | None = None
    prompt: str | None = None
    page_text: str | None = None
    result: str | None = None
