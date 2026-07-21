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


class PromptShortcutId(StrEnum):
    """Stable Prompt Shortcut identities returned by Quick Insight."""

    ANALYZE = "analyze"
    TAILOR_RESUME = "tailor_resume"
    WRITE_COVER_LETTER = "write_cover_letter"
    ASK_MORE = "ask_more"


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
# Assistant histories and complete Artifact drafts share one bounded text cap.
DOCUMENT_TEXT_MAX_CHARS = 100_000
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


class PromptShortcut(BaseModel):
    """Localized editable composer draft declared by a routed Agent."""

    model_config = ConfigDict(extra="forbid")

    id: PromptShortcutId
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    prompt: str = Field(max_length=USER_MESSAGE_MAX_CHARS)


class WorkspaceDescriptor(BaseModel):
    """Quick Insight returned stable client Workspace identity."""

    model_config = ConfigDict(extra="forbid")

    resource_url: str


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
        if artifact.version != artifact.attachment.version:
            raise ValueError("Artifact version must equal its Attachment version")
        if latest_attachment_by_type.get(artifact_type) != artifact.attachment:
            raise ValueError("Artifact Attachment must equal the latest Attachment of its type")


MAX_WORKSPACE_TURNS = 10
MAX_FRESH_WORKSPACE_HISTORIES = MAX_WORKSPACE_TURNS * 2
MAX_WORKSPACE_HISTORIES = 11 + MAX_FRESH_WORKSPACE_HISTORIES


def count_user_turns(histories: list[HistoryMessage]) -> int:
    """Count completed canonical user sends in shared Workspace history."""

    return sum(message.role == "user" for message in histories)


class WorkspaceRequest(PageContext):
    """One message-only protocol-v4 Workspace transition request."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_url: str = Field(alias="resourceUrl")
    operation_id: UUID = Field(alias="operationId")
    histories: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=MAX_WORKSPACE_HISTORIES,
    )
    artifacts: Artifacts
    message: str = Field(min_length=1, max_length=USER_MESSAGE_MAX_CHARS)

    @model_validator(mode="after")
    def validate_workspace_request(self) -> "WorkspaceRequest":
        """Validate canonical state and reserve the next user turn."""

        validate_workspace_state(self.histories, self.artifacts)
        user_turns = count_user_turns(self.histories)
        if user_turns >= MAX_WORKSPACE_TURNS:
            raise ValueError("Workspace already contains 10 user turns")
        assistant_turns = len(self.histories) - user_turns
        if not user_turns <= assistant_turns <= user_turns + 11:
            raise ValueError(
                "Workspace history role balance must satisfy U <= A <= U + 11"
            )
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
    """Agent result that creates a complete first Artifact snapshot."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[WorkspaceResultType.CREATE_ARTIFACT]
    markdown: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)
    artifact_type: ArtifactType
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    draft: str = Field(max_length=DOCUMENT_TEXT_MAX_CHARS)


class UpdateArtifactResult(BaseModel):
    """Agent result that replaces one existing Artifact snapshot."""

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

    model_config = ConfigDict(extra="forbid")

    request: QuickInsightRequest
    insight: Insight
    shortcuts: list[PromptShortcut] = Field(default_factory=list)
    workspace: WorkspaceDescriptor
    meta: ExecutionMeta = Field(default_factory=ExecutionMeta)
    protocol_version: Literal[CURRENT_EXTENSION_PROTOCOL_VERSION] = (
        CURRENT_EXTENSION_PROTOCOL_VERSION
    )


class WorkspaceResponse(BaseModel):
    """Protocol-v4 terminal Workspace response returned to the Extension."""

    model_config = ConfigDict(extra="forbid")

    resource_url: str
    result_type: WorkspaceResultType
    histories: list[HistoryMessage] = Field(max_length=MAX_WORKSPACE_HISTORIES)
    artifacts: Artifacts
    meta: ExecutionMeta = Field(default_factory=ExecutionMeta)
    protocol_version: Literal[CURRENT_EXTENSION_PROTOCOL_VERSION] = (
        CURRENT_EXTENSION_PROTOCOL_VERSION
    )

    @model_validator(mode="after")
    def validate_response_state(self) -> "WorkspaceResponse":
        """Apply the same state invariants used for incoming Workspace state."""

        validate_workspace_state(self.histories, self.artifacts)
        return self
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
