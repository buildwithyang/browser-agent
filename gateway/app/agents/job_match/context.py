from dataclasses import dataclass

from app.modules.task.schema import Artifacts, HistoryMessage, WorkspaceRequest


@dataclass(frozen=True)
class JobChatContext:
    """Complete request-scoped state used by the Job Match orchestrator."""

    request: WorkspaceRequest
    resume_text: str
    histories: tuple[HistoryMessage, ...]
    artifacts: Artifacts
    current_message: str
