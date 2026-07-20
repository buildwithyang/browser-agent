import os
from pathlib import Path

from pypdf import PdfReader

from app.agents.base import (
    AgentContext,
    AgentExecution,
    OpenAIChatAgent,
    QuickInsightAgent,
)
from app.agents.job_match.legacy import LegacyJobMatchExecutor, SYSTEM_PROMPT
from app.agents.job_match.quick_insight import (
    MIN_JOB_CONTENT_CHARS,
    WORKSPACE_ACTION_TITLES,
    JobQuickInsightAgent,
    validate_job_request,
)
from app.modules.task.schema import (
    Action,
    ActionId,
    AgentName,
    DocumentContent,
    Insight,
    WorkspaceRequest,
)

DEFAULT_CV_PATH = os.environ.get("AGENT_BRIDGE_CV_PATH", "data/cv/cv.pdf")
JOB_WORKSPACE_ACTION_IDS = (
    ActionId.ANALYZE,
    ActionId.TAILOR_RESUME,
    ActionId.WRITE_COVER_LETTER,
    ActionId.ASK_MORE,
)


class JobMatchAgent(OpenAIChatAgent, QuickInsightAgent):
    """Stateless facade for job Quick Insight and temporary legacy execution."""

    name = AgentName.JOB_MATCH
    requires_resume = True
    system_prompt = SYSTEM_PROMPT

    def __init__(self, *args, cv_path: str | Path | None = None, **kwargs) -> None:
        """Build stateless delegates around shared model and CV-loading dependencies."""

        super().__init__(*args, **kwargs)
        self.cv_path = Path(cv_path or DEFAULT_CV_PATH)
        self._quick_insight = JobQuickInsightAgent(
            complete_prompt=self.complete_prompt,
            resolve_resume_text=self._resolve_resume_text,
        )
        self._legacy = LegacyJobMatchExecutor(
            complete_prompt=self.complete_prompt,
            resolve_resume_text=self._resolve_resume_text,
        )

    def _resolve_resume_text(self, injected_text: str | None) -> str:
        """Use injected user text or reload the anonymous local CV without caching it."""

        if injected_text and injected_text.strip():
            return injected_text
        return self._read_cv()

    def _read_cv(self) -> str:
        """Read the configured single-user fallback CV for the current request."""

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

    def validate(self, context: AgentContext) -> None:
        """Validate job evidence and transitional v1 Workspace Actions."""

        validate_job_request(context.request)
        if isinstance(context.request, WorkspaceRequest):
            self._legacy.validate_workspace_action(context.request)

    def actions(self, context: AgentContext) -> list[Action]:
        """Bridge the transitional TaskAgent Action contract."""

        return self.available_actions(context)

    def available_actions(self, context: AgentContext) -> list[Action]:
        """Declare the ordered job Workspace Actions for the request language."""

        title_lang = "en" if context.request.lang == "en" else "zh"
        titles = WORKSPACE_ACTION_TITLES[title_lang]
        return [
            Action(id=action_id, title=titles[action_id])
            for action_id in JOB_WORKSPACE_ACTION_IDS
        ]

    def insight(self, context: AgentContext) -> AgentExecution[Insight]:
        """Bridge the transitional TaskAgent insight contract."""

        return self.quick_insight(context)

    def quick_insight(self, context: AgentContext) -> AgentExecution[Insight]:
        """Delegate a stateless decision-first Quick Insight operation."""

        return self._quick_insight.execute(context)

    def execute(self, context: AgentContext) -> AgentExecution[DocumentContent]:
        """Delegate the temporary v1 document flow until the Task 8 shim."""

        return self._legacy.execute(context)


__all__ = ["JobMatchAgent", "MIN_JOB_CONTENT_CHARS"]
