from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "successful"
    data: T


class AgentName(StrEnum):
    """稳定的 Agent 标识；HTTP/DB 边界仍使用成员的字符串值。"""

    BROWSER_AGENT = "browser_agent"
    SUMMARY_PAGE = "summary_page"
    JOB_MATCH = "job_match"
    # 未来外部适配预留，暂未实现。
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    OPENCLAW = "openclaw"


class ActionId(StrEnum):
    """Workspace 支持的稳定 Action 标识。"""

    ANALYZE = "analyze"
    TAILOR_RESUME = "tailor_resume"
    WRITE_COVER_LETTER = "write_cover_letter"
    ASK_MORE = "ask_more"


Recommendation = Literal["strong_apply", "apply", "cautious", "skip"]

# /tasks 输入封顶：防止匿名/恶意调用塞超大正文烧平台 LLM 钱。
PAGE_TEXT_MAX_CHARS = 200_000
SELECTED_TEXT_MAX_CHARS = 100_000
IMAGE_TEXT_MAX_CHARS = 50_000
USER_MESSAGE_MAX_CHARS = 10_000
# Assistant histories are copied from DocumentContent.text, so both share one cap.
DOCUMENT_TEXT_MAX_CHARS = 100_000
DOCUMENT_DRAFT_KIND_MAX_CHARS = 100
DOCUMENT_DRAFT_TITLE_MAX_CHARS = 500
DOCUMENT_DRAFT_TEXT_MAX_CHARS = 50_000


class PageContext(BaseModel):
    """浏览器明确提交的当前页面上下文。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    url: str
    title: str = ""
    selected_text: str = Field("", alias="selectedText", max_length=SELECTED_TEXT_MAX_CHARS)
    page_text: str = Field("", alias="pageText", max_length=PAGE_TEXT_MAX_CHARS)
    # 图片文字线索(alt / caption / aria-label),纯文本,不含图片本身。
    image_text: str = Field("", alias="imageText", max_length=IMAGE_TEXT_MAX_CHARS)
    intent: str = "Summarize this page."
    # 输出语言:"zh"/"en" 强制;"auto" 跟随页面语言。扩展通常已把用户偏好解析为 zh/en。
    lang: Literal["auto", "zh", "en"] = "auto"


class QuickInsightRequest(PageContext):
    """Quick Insight 场景输入；只产生 Insight，不产生文档区块。"""


class TaskRequest(PageContext):
    """旧 `/tasks` 内部执行输入；不属于新的公共 wire contract。"""

    action_id: str = Field(alias="actionId", min_length=1, max_length=100)
    prior_result: str | None = Field(default=None, alias="priorResult", max_length=50_000)
    message: str = Field(default="", max_length=USER_MESSAGE_MAX_CHARS)


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


class InsightItem(BaseModel):
    label: str
    value: str


class ScoreInsightCard(BaseModel):
    type: Literal["score"] = "score"
    id: str
    title: str
    score: int = Field(ge=0, le=100)
    max_score: int = Field(default=100, ge=1)
    recommendation: Recommendation
    reason: str


class TextInsightCard(BaseModel):
    type: Literal["text"] = "text"
    id: str
    title: str
    body_html: str


class DetailsInsightCard(BaseModel):
    type: Literal["details"] = "details"
    id: str
    title: str
    items: list[InsightItem] = Field(default_factory=list)
    summary: str = ""


InsightCard = Annotated[
    ScoreInsightCard | TextInsightCard | DetailsInsightCard,
    Field(discriminator="type"),
]


class Insight(BaseModel):
    title: str
    cards: list[InsightCard] = Field(default_factory=list)


class Action(BaseModel):
    """后端声明的 Current Task 入口；执行参数由后端按 id 解析。"""

    id: str
    title: str


class WorkspaceDescriptor(BaseModel):
    """Quick Insight 返回的客户端 Workspace 身份和默认 Action。"""

    resource_url: str
    default_action_id: ActionId


class HistoryMessage(BaseModel):
    """一次 Workspace 用户或 Assistant 消息。"""

    id: UUID = Field(default_factory=uuid4)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)
    action_id: ActionId | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_user_content(self) -> "HistoryMessage":
        """Apply the smaller interactive-input limit only to user history."""

        if self.role == "user" and not 1 <= len(self.content) <= USER_MESSAGE_MAX_CHARS:
            raise ValueError(
                f"user history content must contain 1 to {USER_MESSAGE_MAX_CHARS} characters"
            )
        return self


class DocumentDraft(BaseModel):
    """客户端回传的最新文档草稿，供本次无状态生成使用。"""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field("", max_length=DOCUMENT_DRAFT_KIND_MAX_CHARS)
    title: str = Field("", max_length=DOCUMENT_DRAFT_TITLE_MAX_CHARS)
    text: str = Field("", max_length=DOCUMENT_DRAFT_TEXT_MAX_CHARS)


class WorkspaceRequest(PageContext):
    """共享 Workspace 的一次无状态 Action 请求。"""

    resource_url: str = Field(alias="resourceUrl")
    action_id: ActionId = Field(alias="actionId")
    histories: list[HistoryMessage] = Field(default_factory=list, max_length=10)
    current_document: DocumentDraft | None = Field(
        default=None,
        alias="currentDocument",
    )
    message: str = Field(min_length=1, max_length=USER_MESSAGE_MAX_CHARS)

    @model_validator(mode="after")
    def validate_message_limit(self) -> "WorkspaceRequest":
        """Count the current user message against the ten-message input cap."""

        if len(self.histories) + 1 > 10:
            raise ValueError("histories plus current message must not exceed 10")
        return self


class DocumentContent(BaseModel):
    """Agent 生成并返回给客户端的最新文档。"""

    kind: str = ""
    title: str = ""
    text: str = Field("", max_length=DOCUMENT_TEXT_MAX_CHARS)
    html: str = ""
    sections: list[Section] = Field(default_factory=list)


class ExecutionMeta(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["completed", "failed"] = "completed"
    input_chars: int = 0
    model: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class QuickInsightResponse(BaseModel):
    request: QuickInsightRequest
    insight: Insight
    actions: list[Action] = Field(default_factory=list)
    workspace: WorkspaceDescriptor
    meta: ExecutionMeta = Field(default_factory=ExecutionMeta)


class WorkspaceResponse(BaseModel):
    """Workspace 单次状态转换的完整结果。"""

    resource_url: str
    selected_action_id: ActionId
    histories: list[HistoryMessage]
    document: DocumentContent | None
    meta: ExecutionMeta = Field(default_factory=ExecutionMeta)


class TaskResponse(BaseModel):
    """已部署 legacy `/tasks` 的内部文档响应。"""

    request: TaskRequest
    document: DocumentContent
    meta: ExecutionMeta = Field(default_factory=ExecutionMeta)


class TaskRecordData(BaseModel):
    """落库的任务记录领域对象。

    Repository/DB 配置时，service 会填充可用的任务明细字段。
    这些字段含隐私，不会回传给前端（recent 列表不读取它们）。
    """

    id: str
    user_id: str | None = None
    agent: AgentName
    lang: str = "auto"
    model: str = ""
    status: str = "completed"
    input_chars: int = 0
    result_chars: int = 0
    duration_ms: int | None = None
    error: str = ""
    created_at: datetime
    # 任务明细（缺少页面上下文或失败时可为 None）。
    url: str | None = None
    title: str | None = None
    prompt: str | None = None
    page_text: str | None = None
    result: str | None = None
