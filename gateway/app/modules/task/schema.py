from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.task.protocol import CURRENT_EXTENSION_PROTOCOL_VERSION

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


class WorkspaceTrigger(StrEnum):
    """Stable entry modes for one stateless Workspace transition."""

    USER_MESSAGE = "user_message"
    QUICK_INSIGHT_ACTION = "quick_insight_action"


class WorkspaceResultType(StrEnum):
    """Possible final outcomes reported by the Workspace reducer."""

    REPLY = "reply"
    CREATE_ARTIFACT = "create_artifact"
    UPDATE_ARTIFACT = "update_artifact"


class ArtifactType(StrEnum):
    """The two versioned Workspace artifact categories."""

    CV = "cv"
    COVER_LETTER = "cover_letter"


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
# Preserve every valid generated document across the next stateless Workspace turn.
DOCUMENT_DRAFT_TEXT_MAX_CHARS = DOCUMENT_TEXT_MAX_CHARS
ATTACHMENT_CV_CONTENT_MAX_CHARS = 4_096
TITLE_MAX_CHARS = 500
ARTIFACT_VERSION_MAX = 2_147_483_647


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


class Attachment(BaseModel):
    """An immutable Artifact version snapshot embedded in an Assistant message."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    artifact_id: UUID
    version: int = Field(ge=1, le=ARTIFACT_VERSION_MAX)
    type: ArtifactType
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    content: str = Field(min_length=1, max_length=DOCUMENT_TEXT_MAX_CHARS)

    @model_validator(mode="after")
    def validate_content_for_type(self) -> "Attachment":
        """Enforce the URL-only CV attachment representation."""

        if self.type is ArtifactType.CV:
            parsed = urlparse(self.content)
            if (
                len(self.content) > ATTACHMENT_CV_CONTENT_MAX_CHARS
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
            ):
                raise ValueError("CV Attachment content must be an absolute HTTP(S) URL")
        return self


class Artifact(BaseModel):
    """The latest complete snapshot of one Workspace artifact category."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    type: ArtifactType
    version: int = Field(ge=1, le=ARTIFACT_VERSION_MAX)
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    draft: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)
    attachment: Attachment


class Artifacts(BaseModel):
    """Fixed-key latest Artifact map carried in every Workspace state."""

    model_config = ConfigDict(extra="forbid")

    cv: Artifact | None
    cover_letter: Artifact | None


class HistoryMessage(BaseModel):
    """One complete Workspace message supplied by or returned to the Extension."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)
    action_id: ActionId | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: list[Attachment] = Field(default_factory=list, max_length=1)

    @model_validator(mode="after")
    def validate_workspace_message(self) -> "HistoryMessage":
        """Validate role-specific text, Attachment and UTC timestamp constraints."""

        if self.role == "user" and not 1 <= len(self.content) <= USER_MESSAGE_MAX_CHARS:
            raise ValueError(
                f"user history content must contain 1 to {USER_MESSAGE_MAX_CHARS} characters"
            )
        if self.role == "user" and self.attachments:
            raise ValueError("user message attachments must be empty")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("message created_at must be UTC")
        return self


class DocumentDraft(BaseModel):
    """Transitional v1 document input kept until Task 8 migrates consumers."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field("", max_length=DOCUMENT_DRAFT_KIND_MAX_CHARS)
    title: str = Field("", max_length=DOCUMENT_DRAFT_TITLE_MAX_CHARS)
    text: str = Field("", max_length=DOCUMENT_DRAFT_TEXT_MAX_CHARS)


def validate_workspace_state(histories: list[HistoryMessage], artifacts: Artifacts) -> None:
    """Validate cross-object identity, reference and latest-snapshot invariants."""

    message_ids = [message.id for message in histories]
    if len(message_ids) != len(set(message_ids)):
        raise ValueError("message IDs must be unique")

    attachments = [attachment for message in histories for attachment in message.attachments]
    attachment_ids = [attachment.id for attachment in attachments]
    if len(attachment_ids) != len(set(attachment_ids)):
        raise ValueError("Attachment IDs must be unique")

    artifact_by_type = {
        ArtifactType.CV: artifacts.cv,
        ArtifactType.COVER_LETTER: artifacts.cover_letter,
    }
    present_artifacts = [artifact for artifact in artifact_by_type.values() if artifact is not None]
    artifact_ids = [artifact.id for artifact in present_artifacts]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("Artifact IDs must be unique")

    latest_attachment_by_type: dict[ArtifactType, Attachment] = {}
    for attachment in attachments:
        referenced_artifact = artifact_by_type[attachment.type]
        if referenced_artifact is None or attachment.artifact_id != referenced_artifact.id:
            raise ValueError("Attachment artifact_id must reference its current Artifact")
        latest_attachment_by_type[attachment.type] = attachment

    for artifact_type, artifact in artifact_by_type.items():
        if artifact is None:
            continue
        if artifact.type is not artifact_type:
            raise ValueError("Artifact type must match its Artifacts key")
        if artifact.attachment.artifact_id != artifact.id:
            raise ValueError("Artifact Attachment artifact_id must match its Artifact")
        if latest_attachment_by_type.get(artifact_type) != artifact.attachment:
            raise ValueError("Artifact Attachment must equal the latest Attachment of its type")


class WorkspaceRequestBase(PageContext):
    """Shared fields for the two intentionally disjoint Workspace triggers."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_url: str = Field(alias="resourceUrl")
    action_id: ActionId = Field(alias="actionId")
    histories: list[HistoryMessage] = Field(default_factory=list, max_length=10)
    artifacts: Artifacts


class UserMessageWorkspaceRequest(WorkspaceRequestBase):
    """Workspace request that appends one non-empty user message before execution."""

    trigger: Literal[WorkspaceTrigger.USER_MESSAGE]
    message: str = Field(min_length=1, max_length=USER_MESSAGE_MAX_CHARS)

    @model_validator(mode="after")
    def validate_user_message_state(self) -> "UserMessageWorkspaceRequest":
        """Reserve one of the ten incoming message slots for the user text."""

        if len(self.histories) > 9:
            raise ValueError("user_message histories must contain at most 9 messages")
        validate_workspace_state(self.histories, self.artifacts)
        return self


class QuickInsightActionWorkspaceRequest(WorkspaceRequestBase):
    """Workspace request triggered by a deterministic Quick Insight Action."""

    trigger: Literal[WorkspaceTrigger.QUICK_INSIGHT_ACTION]

    @model_validator(mode="after")
    def validate_quick_insight_action_state(self) -> "QuickInsightActionWorkspaceRequest":
        """Validate the complete pre-existing state without appending a user message."""

        validate_workspace_state(self.histories, self.artifacts)
        return self


WorkspaceChatRequest = Annotated[
    UserMessageWorkspaceRequest | QuickInsightActionWorkspaceRequest,
    Field(discriminator="trigger"),
]


class DocumentContent(BaseModel):
    """Transitional v1 document output kept until Task 8 migrates consumers."""

    kind: str = ""
    title: str = ""
    text: str = Field("", max_length=DOCUMENT_TEXT_MAX_CHARS)
    html: str = ""
    sections: list[Section] = Field(default_factory=list)


class WorkspaceRequest(PageContext):
    """Transitional v1 Workspace input kept for unmigrated runtime consumers."""

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
        """Count the current user message against the legacy ten-message input cap."""

        if len(self.histories) + 1 > 10:
            raise ValueError("histories plus current message must not exceed 10")
        return self


class ExecutionMeta(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["completed", "failed"] = "completed"
    input_chars: int = 0
    model: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class ReplyResult(BaseModel):
    """Markdown-only Agent result that does not create an Artifact."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[WorkspaceResultType.REPLY]
    markdown: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)


class CreateArtifactResult(BaseModel):
    """Markdown Agent result that creates a complete first Artifact snapshot."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[WorkspaceResultType.CREATE_ARTIFACT]
    markdown: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)
    artifact_type: ArtifactType
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    draft: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)


class UpdateArtifactResult(BaseModel):
    """Markdown Agent result that replaces one existing Artifact snapshot."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[WorkspaceResultType.UPDATE_ARTIFACT]
    markdown: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)
    artifact_type: ArtifactType
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    draft: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)


ChatResult = Annotated[
    ReplyResult | CreateArtifactResult | UpdateArtifactResult,
    Field(discriminator="type"),
]


class QuickInsightResponse(BaseModel):
    """Quick Insight response with its stable extension protocol marker."""

    request: QuickInsightRequest
    insight: Insight
    actions: list[Action] = Field(default_factory=list)
    workspace: WorkspaceDescriptor
    meta: ExecutionMeta = Field(default_factory=ExecutionMeta)
    protocol_version: Literal[CURRENT_EXTENSION_PROTOCOL_VERSION] = (
        CURRENT_EXTENSION_PROTOCOL_VERSION
    )


class WorkspaceChatResponse(BaseModel):
    """Protocol-v2 Markdown-only complete Workspace state returned to the Extension."""

    model_config = ConfigDict(extra="forbid")

    resource_url: str
    selected_action_id: ActionId
    result_type: WorkspaceResultType
    histories: list[HistoryMessage] = Field(max_length=11)
    artifacts: Artifacts
    meta: ExecutionMeta = Field(default_factory=ExecutionMeta)
    protocol_version: Literal[CURRENT_EXTENSION_PROTOCOL_VERSION] = (
        CURRENT_EXTENSION_PROTOCOL_VERSION
    )

    @model_validator(mode="after")
    def validate_response_state(self) -> "WorkspaceChatResponse":
        """Apply the same state invariants used for both incoming trigger variants."""

        validate_workspace_state(self.histories, self.artifacts)
        return self


class WorkspaceResponse(BaseModel):
    """Transitional v1 Workspace document response kept for runtime compatibility."""

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
