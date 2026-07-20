from dataclasses import dataclass

from app.modules.task.schema import (
    ActionId,
    Artifacts,
    HistoryMessage,
    WorkspaceChatRequest,
    WorkspaceTrigger,
)


@dataclass(frozen=True)
class JobChatContext:
    """Immutable request-scoped state for one future job Workspace transition."""

    trigger: WorkspaceTrigger
    request: WorkspaceChatRequest
    resume_text: str | None
    histories: tuple[HistoryMessage, ...]
    artifacts: Artifacts
    selected_action: ActionId
    current_message: str | None = None
