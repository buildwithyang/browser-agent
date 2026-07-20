import os
from collections.abc import Mapping
from pathlib import Path

from pypdf import PdfReader

from app.agents.base import (
    AgentContext,
    AgentExecution,
    OpenAIChatAgent,
    QuickInsightAgent,
    WorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.job_match.context import JobChatContext
from app.agents.job_match.legacy import LegacyJobMatchExecutor, SYSTEM_PROMPT
from app.agents.job_match.quick_insight import (
    MIN_JOB_CONTENT_CHARS,
    WORKSPACE_ACTION_TITLES,
    JobQuickInsightAgent,
    validate_job_request,
)
from app.agents.job_match.router import IntentRouter, SpecialistId
from app.agents.job_match.specialists.analysis import JobAnalysisAgent
from app.agents.job_match.specialists.base import (
    ArtifactDraftResult,
    JobMatchSpecialist,
    SpecialistReply,
    SpecialistResult,
)
from app.agents.job_match.specialists.cover_letter import CoverLetterAgent
from app.agents.job_match.specialists.general_qa import GeneralQAAgent
from app.agents.job_match.specialists.resume import ResumeTailoringAgent
from app.modules.task.schema import (
    Action,
    ActionId,
    AgentName,
    Artifact,
    ArtifactType,
    ChatResult,
    CreateArtifactResult,
    DocumentContent,
    Insight,
    ReplyResult,
    UpdateArtifactResult,
    WorkspaceResultType,
    WorkspaceRequest,
    WorkspaceTrigger,
)

DEFAULT_CV_PATH = os.environ.get("AGENT_BRIDGE_CV_PATH", "data/cv/cv.pdf")
JOB_WORKSPACE_ACTION_IDS = (
    ActionId.ANALYZE,
    ActionId.TAILOR_RESUME,
    ActionId.WRITE_COVER_LETTER,
    ActionId.ASK_MORE,
)

QUICK_SPECIALIST_BY_ACTION = {
    ActionId.ANALYZE: SpecialistId.JOB_ANALYSIS,
    ActionId.TAILOR_RESUME: SpecialistId.RESUME,
    ActionId.WRITE_COVER_LETTER: SpecialistId.COVER_LETTER,
}
"""Deterministic Quick Action to Specialist command mapping."""

LEGAL_ARTIFACT_BY_SPECIALIST = {
    SpecialistId.JOB_ANALYSIS: None,
    SpecialistId.RESUME: ArtifactType.CV,
    SpecialistId.COVER_LETTER: ArtifactType.COVER_LETTER,
    SpecialistId.GENERAL_QA: None,
}
"""Artifact result owned by each Specialist, or ``None`` for reply-only Strategies."""


class JobMatchOrchestrationError(RuntimeError):
    """Raised when a Workspace command cannot produce a legal final chat result."""


class JobMatchAgent(OpenAIChatAgent, QuickInsightAgent, WorkspaceAgent):
    """Stateless Facade/Mediator for all job-match execution paths."""

    name = AgentName.JOB_MATCH
    requires_resume = True
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        *args,
        cv_path: str | Path | None = None,
        intent_router: IntentRouter | None = None,
        specialists: Mapping[SpecialistId, JobMatchSpecialist] | None = None,
        **kwargs,
    ) -> None:
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
        self._intent_router = intent_router or IntentRouter(
            complete_prompt=self.complete_prompt
        )
        self._specialists = (
            dict(specialists) if specialists is not None else self._build_specialists()
        )

    def _build_specialists(self) -> dict[SpecialistId, JobMatchSpecialist]:
        """Build the production Strategy registry over the shared completion boundary."""

        return {
            SpecialistId.JOB_ANALYSIS: JobAnalysisAgent(
                complete_prompt=self.complete_prompt
            ),
            SpecialistId.RESUME: ResumeTailoringAgent(
                complete_prompt=self.complete_prompt
            ),
            SpecialistId.COVER_LETTER: CoverLetterAgent(
                complete_prompt=self.complete_prompt
            ),
            SpecialistId.GENERAL_QA: GeneralQAAgent(
                complete_prompt=self.complete_prompt
            ),
        }

    def _to_job_chat_context(self, context: WorkspaceAgentContext) -> JobChatContext:
        """Adapt the public immutable Agent context to the job domain context."""

        request = context.request
        return JobChatContext(
            trigger=request.trigger,
            request=request,
            resume_text=context.resume_text,
            histories=tuple(request.histories),
            artifacts=request.artifacts,
            selected_action=request.action_id,
            current_message=getattr(request, "message", None),
        )

    def _select_specialist(self, context: JobChatContext) -> SpecialistId:
        """Route a user message or resolve a deterministic Quick command directly."""

        if context.trigger is WorkspaceTrigger.USER_MESSAGE:
            return self._intent_router.route(context).specialist
        if context.selected_action is ActionId.ASK_MORE:
            raise JobMatchOrchestrationError(
                "ask_more is not a backend Quick Insight Action command"
            )
        try:
            return QUICK_SPECIALIST_BY_ACTION[context.selected_action]
        except KeyError as exc:
            raise JobMatchOrchestrationError(
                f"unsupported Quick Insight Action: {context.selected_action.value}"
            ) from exc

    def _execute_specialist(
        self,
        specialist_id: SpecialistId,
        context: JobChatContext,
    ) -> AgentExecution[SpecialistResult]:
        """Execute exactly one registered Strategy for the selected Specialist id."""

        try:
            specialist = self._specialists[specialist_id]
        except KeyError as exc:
            raise JobMatchOrchestrationError(
                f"no Specialist registered for {specialist_id.value}"
            ) from exc
        return specialist.handle(context)

    def _validate_specialist_result(
        self,
        specialist_id: SpecialistId,
        result: object,
    ) -> SpecialistResult:
        """Enforce the complete Specialist-to-result legal matrix at the Facade boundary."""

        if isinstance(result, SpecialistReply):
            return result
        expected_artifact = LEGAL_ARTIFACT_BY_SPECIALIST[specialist_id]
        if (
            isinstance(result, ArtifactDraftResult)
            and expected_artifact is not None
            and result.artifact_type is expected_artifact
        ):
            return result
        raise JobMatchOrchestrationError(
            f"illegal Specialist result for {specialist_id.value}"
        )

    def _validate_quick_result(
        self,
        action_id: ActionId,
        result: object,
    ) -> None:
        """Apply the stricter deterministic Quick Action result matrix."""

        if action_id is ActionId.ANALYZE and isinstance(result, SpecialistReply):
            return
        expected_artifact = {
            ActionId.TAILOR_RESUME: ArtifactType.CV,
            ActionId.WRITE_COVER_LETTER: ArtifactType.COVER_LETTER,
        }.get(action_id)
        if (
            expected_artifact is not None
            and isinstance(result, ArtifactDraftResult)
            and result.artifact_type is expected_artifact
        ):
            return
        raise JobMatchOrchestrationError(
            f"illegal result for Quick Insight Action {action_id.value}"
        )

    def _existing_artifact(
        self,
        context: JobChatContext,
        artifact_type: ArtifactType,
    ) -> Artifact | None:
        """Read only the same-type Artifact slot used for create/update normalization."""

        if artifact_type is ArtifactType.CV:
            return context.artifacts.cv
        return context.artifacts.cover_letter

    def _normalize_result(
        self,
        context: JobChatContext,
        result: SpecialistResult,
    ) -> ChatResult:
        """Convert one validated Specialist result to the public Workspace result union."""

        if isinstance(result, SpecialistReply):
            return ReplyResult(
                type=WorkspaceResultType.REPLY,
                markdown=result.markdown,
            )
        result_class: type[CreateArtifactResult] | type[UpdateArtifactResult]
        result_type: WorkspaceResultType
        if self._existing_artifact(context, result.artifact_type) is None:
            result_class = CreateArtifactResult
            result_type = WorkspaceResultType.CREATE_ARTIFACT
        else:
            result_class = UpdateArtifactResult
            result_type = WorkspaceResultType.UPDATE_ARTIFACT
        return result_class(
            type=result_type,
            markdown=result.markdown,
            artifact_type=result.artifact_type,
            title=result.title,
            draft=result.draft,
        )

    def handle_chat(
        self,
        context: WorkspaceAgentContext,
    ) -> AgentExecution[ChatResult]:
        """Coordinate Router and one Specialist without allocating persistent state."""

        job_context = self._to_job_chat_context(context)
        specialist_id = self._select_specialist(job_context)
        specialist_execution = self._execute_specialist(specialist_id, job_context)
        if job_context.trigger is WorkspaceTrigger.QUICK_INSIGHT_ACTION:
            self._validate_quick_result(
                job_context.selected_action,
                specialist_execution.content,
            )
        result = self._validate_specialist_result(
            specialist_id,
            specialist_execution.content,
        )
        return AgentExecution(
            content=self._normalize_result(job_context, result),
            raw_result=specialist_execution.raw_result,
            prompt=specialist_execution.prompt,
            model=specialist_execution.model,
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


__all__ = ["JobMatchAgent", "JobMatchOrchestrationError", "MIN_JOB_CONTENT_CHARS"]
