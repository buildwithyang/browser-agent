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
AgentName = Literal["summary_page", "job_match", "claude-code", "codex", "openclaw"]


class TaskCreate(BaseModel):
    """浏览器扩展提交的任务（agent 的输入契约）。

    扩展发送扁平的 camelCase 负载(``{url, title, selectedText, pageText}``)，
    这里用别名接收，同时对网关其余部分暴露 snake_case 属性。
    """

    model_config = ConfigDict(populate_by_name=True)

    url: str
    title: str = ""
    selected_text: str = Field("", alias="selectedText")
    page_text: str = Field("", alias="pageText")
    # 图片文字线索(alt / caption / aria-label),纯文本,不含图片本身。
    image_text: str = Field("", alias="imageText")
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
    error: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class TaskRecordData(BaseModel):
    """落库的任务记录领域对象：metrics-only，不含 prompt / 结果文本 / 页面正文。"""

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
