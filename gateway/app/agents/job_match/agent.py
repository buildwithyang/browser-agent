"""Stateless streaming Facade for Job Match Quick Insight and Workspace chat."""

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

from pypdf import PdfReader

from app.agents.base import (
    AgentContext,
    AgentExecution,
    OpenAIChatAgent,
    QuickInsightAgent,
    StreamingWorkspaceAgent,
    WorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.job_match.context import JobChatContext
from app.agents.job_match.planner import ChatPlan, ChatPlanner, OutputMode, SpecialistId
from app.agents.job_match.quick_insight import (
    MIN_JOB_CONTENT_CHARS,
    PROMPT_SHORTCUT_CATALOGUES,
    JobQuickInsightAgent,
)
from app.agents.job_match.specialists.analysis import JobAnalysisAgent
from app.agents.job_match.specialists.base import JobMatchSpecialist, SpecialistTextStream
from app.agents.job_match.specialists.cover_letter import CoverLetterAgent
from app.agents.job_match.specialists.general_qa import GeneralQAAgent
from app.agents.job_match.specialists.resume import ResumeTailoringAgent
from app.agents.stream import (
    AgentCompleted,
    AgentDelta,
    AgentStatus,
    AgentStreamEvent,
    closing_if_supported,
)
from app.modules.task.schema import (
    AgentName,
    Artifact,
    ArtifactType,
    ChatResult,
    CreateArtifactResult,
    DOCUMENT_TEXT_MAX_CHARS,
    Insight,
    PromptShortcut,
    ReplyResult,
    UpdateArtifactResult,
    WorkspaceResultType,
)

DEFAULT_CV_PATH = os.environ.get("AGENT_BRIDGE_CV_PATH", "data/cv/cv.pdf")
ARTIFACT_BY_SPECIALIST = {
    SpecialistId.RESUME: ArtifactType.CV,
    SpecialistId.COVER_LETTER: ArtifactType.COVER_LETTER,
}
"""Artifact type owned by each Artifact-capable Specialist."""

ARTIFACT_TITLES = {
    "en": {
        ArtifactType.CV: "Tailored CV",
        ArtifactType.COVER_LETTER: "Cover Letter",
    },
    "zh": {
        ArtifactType.CV: "定制简历",
        ArtifactType.COVER_LETTER: "求职信",
    },
}
"""Deterministic localized titles for complete Workspace Artifacts."""

ARTIFACT_NOTES = {
    "en": {
        (ArtifactType.CV, False): "Created the tailored CV.",
        (ArtifactType.CV, True): "Updated the tailored CV.",
        (ArtifactType.COVER_LETTER, False): "Created the cover letter.",
        (ArtifactType.COVER_LETTER, True): "Updated the cover letter.",
    },
    "zh": {
        (ArtifactType.CV, False): "已创建定制简历。",
        (ArtifactType.CV, True): "已更新定制简历。",
        (ArtifactType.COVER_LETTER, False): "已创建求职信。",
        (ArtifactType.COVER_LETTER, True): "已更新求职信。",
    },
}
"""Deterministic localized Assistant notes for create and update outcomes."""


class JobMatchOrchestrationError(RuntimeError):
    """Raised when a Workspace command cannot produce a legal final chat result."""


class JobMatchAgent(
    OpenAIChatAgent,
    QuickInsightAgent,
    WorkspaceAgent,
    StreamingWorkspaceAgent,
):
    """Stateless Facade/Mediator for all job-match execution paths."""

    name = AgentName.JOB_MATCH
    requires_resume = True

    def __init__(
        self,
        *args: object,
        cv_path: str | Path | None = None,
        planner: ChatPlanner | None = None,
        specialists: Mapping[SpecialistId, JobMatchSpecialist] | None = None,
        **kwargs: object,
    ) -> None:
        """Build stateless delegates around shared model and CV-loading dependencies."""

        super().__init__(*args, **kwargs)
        self.cv_path = Path(cv_path or DEFAULT_CV_PATH)
        self._quick_insight = JobQuickInsightAgent(
            complete_prompt=self.complete_prompt,
            resolve_resume_text=self._resolve_resume_text,
        )
        self._planner = planner or ChatPlanner(complete_prompt=self.acomplete_prompt)
        self._specialists = (
            dict(specialists) if specialists is not None else self._build_specialists()
        )

    def _build_specialists(self) -> dict[SpecialistId, JobMatchSpecialist]:
        """Build the production Strategy registry over the shared stream boundary."""

        return {
            SpecialistId.JOB_ANALYSIS: JobAnalysisAgent(
                open_prompt_stream=self.open_prompt_stream
            ),
            SpecialistId.RESUME: ResumeTailoringAgent(
                open_prompt_stream=self.open_prompt_stream
            ),
            SpecialistId.COVER_LETTER: CoverLetterAgent(
                open_prompt_stream=self.open_prompt_stream
            ),
            SpecialistId.GENERAL_QA: GeneralQAAgent(
                open_prompt_stream=self.open_prompt_stream
            ),
        }

    def _to_job_chat_context(self, context: WorkspaceAgentContext) -> JobChatContext:
        """Adapt the public immutable Agent context to the job domain context."""

        request = context.request
        resume_text = context.resume_text
        if not resume_text or not resume_text.strip():
            raise JobMatchOrchestrationError(
                "Job Match Workspace context is missing resolved resume text"
            )
        return JobChatContext(
            request=request,
            resume_text=resume_text,
            histories=tuple(request.histories),
            artifacts=request.artifacts,
            current_message=request.message,
        )

    def prepare_workspace_context(
        self,
        context: WorkspaceAgentContext,
    ) -> WorkspaceAgentContext:
        """Resolve the authenticated or local fallback CV before streaming starts."""

        return WorkspaceAgentContext(
            request=context.request,
            resume_text=self._resolve_resume_text(context.resume_text),
        )

    async def _select_plan(self, context: JobChatContext) -> ChatPlan:
        """Plan every message from current request-scoped Workspace evidence."""

        return await self._planner.plan(context)

    async def _open_specialist_stream(
        self,
        plan: ChatPlan,
        context: JobChatContext,
    ) -> SpecialistTextStream:
        """Open exactly one registered Strategy stream for the validated plan."""

        try:
            specialist = self._specialists[plan.specialist]
        except KeyError as exc:
            raise JobMatchOrchestrationError(
                f"no Specialist registered for {plan.specialist.value}"
            ) from exc
        return await specialist.open_stream(context, plan.output_mode)

    def _artifact_type(self, plan: ChatPlan) -> ArtifactType:
        """Resolve the deterministic Artifact type for one Artifact plan."""

        try:
            return ARTIFACT_BY_SPECIALIST[plan.specialist]
        except KeyError as exc:
            raise JobMatchOrchestrationError(
                f"Specialist cannot create an Artifact: {plan.specialist.value}"
            ) from exc

    def _existing_artifact(
        self,
        context: JobChatContext,
        artifact_type: ArtifactType,
    ) -> Artifact | None:
        """Read only the same-type Artifact slot used for create/update normalization."""

        if artifact_type is ArtifactType.CV:
            return context.artifacts.cv
        return context.artifacts.cover_letter

    def _artifact_result(
        self,
        context: JobChatContext,
        plan: ChatPlan,
        draft: str,
    ) -> ChatResult:
        """Build deterministic create/update metadata around one complete draft."""

        artifact_type = self._artifact_type(plan)
        exists = self._existing_artifact(context, artifact_type) is not None
        result_class: type[CreateArtifactResult] | type[UpdateArtifactResult]
        result_type: WorkspaceResultType
        if exists:
            result_class = UpdateArtifactResult
            result_type = WorkspaceResultType.UPDATE_ARTIFACT
        else:
            result_class = CreateArtifactResult
            result_type = WorkspaceResultType.CREATE_ARTIFACT
        copy_lang = "en" if context.request.lang == "en" else "zh"
        return result_class(
            type=result_type,
            markdown=ARTIFACT_NOTES[copy_lang][(artifact_type, exists)],
            artifact_type=artifact_type,
            title=ARTIFACT_TITLES[copy_lang][artifact_type],
            draft=draft,
        )

    def _validate_complete_markdown(self, markdown: str) -> str:
        """Require one non-blank result within the shared Workspace text cap."""

        if len(markdown) > DOCUMENT_TEXT_MAX_CHARS:
            raise JobMatchOrchestrationError(
                f"Specialist Markdown exceeds {DOCUMENT_TEXT_MAX_CHARS} characters"
            )
        if not markdown.strip():
            raise JobMatchOrchestrationError("Specialist result must contain Markdown")
        return markdown

    async def stream_chat(
        self,
        context: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Yield progress, visible reply deltas, and one validated terminal result."""

        job_context = self._to_job_chat_context(context)
        yield AgentStatus(stage="routing")
        plan = await self._select_plan(job_context)
        artifact_type = (
            self._artifact_type(plan)
            if plan.output_mode is OutputMode.ARTIFACT
            else None
        )
        yield AgentStatus(
            stage=(
                "generating_artifact"
                if plan.output_mode is OutputMode.ARTIFACT
                else "generating_reply"
            ),
            artifact_type=artifact_type,
        )
        opened = await self._open_specialist_stream(plan, job_context)

        # Accumulate all raw chunks for atomic terminal validation. Artifact chunks never
        # cross the Agent event boundary; reply chunks remain visible as Markdown deltas.
        chunks: list[str] = []
        total_chars = 0
        async with closing_if_supported(opened.chunks) as text_chunks:
            async for chunk in text_chunks:
                if not chunk:
                    continue
                total_chars += len(chunk)
                if total_chars > DOCUMENT_TEXT_MAX_CHARS:
                    raise JobMatchOrchestrationError(
                        f"Specialist Markdown exceeds {DOCUMENT_TEXT_MAX_CHARS} characters"
                    )
                chunks.append(chunk)
                if plan.output_mode is OutputMode.REPLY:
                    yield AgentDelta(text=chunk)

        raw_result = self._validate_complete_markdown("".join(chunks))
        result = (
            ReplyResult(type=WorkspaceResultType.REPLY, markdown=raw_result)
            if plan.output_mode is OutputMode.REPLY
            else self._artifact_result(job_context, plan, raw_result)
        )
        yield AgentStatus(stage="finalizing")
        yield AgentCompleted(
            execution=AgentExecution(
                content=result,
                raw_result=raw_result,
                prompt=opened.prompt,
                model=opened.model,
            )
        )

    def handle_chat(
        self,
        context: WorkspaceAgentContext,
    ) -> AgentExecution[ChatResult]:
        """Collect the stream for the synchronous TaskService compatibility boundary."""

        async def collect_terminal() -> AgentExecution[ChatResult]:
            """Consume exactly one stream and return its sole terminal execution."""

            try:
                terminal: AgentExecution[ChatResult] | None = None
                async for event in self.stream_chat(context):
                    if isinstance(event, AgentCompleted):
                        if terminal is not None:
                            raise JobMatchOrchestrationError(
                                "Agent stream emitted multiple terminal results"
                            )
                        terminal = event.execution
                if terminal is None:
                    raise JobMatchOrchestrationError(
                        "Agent stream did not emit a terminal result"
                    )
                return terminal
            finally:
                # The compatibility API creates a fresh loop per request. Internally-owned
                # clients must be closed on that same loop; injected clients remain caller-owned.
                await self._close_owned_async_clients()

        return asyncio.run(collect_terminal())

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

    def available_shortcuts(self, context: AgentContext) -> list[PromptShortcut]:
        """Declare ordered localized editable Prompt Shortcuts for a job page."""

        copy_lang = "zh" if context.request.lang == "zh" else "en"
        return [
            PromptShortcut(id=shortcut_id, title=title, prompt=prompt)
            for shortcut_id, title, prompt in PROMPT_SHORTCUT_CATALOGUES[copy_lang]
        ]

    def quick_insight(self, context: AgentContext) -> AgentExecution[Insight]:
        """Delegate a stateless decision-first Quick Insight operation."""

        return self._quick_insight.execute(context)


__all__ = ["JobMatchAgent", "JobMatchOrchestrationError", "MIN_JOB_CONTENT_CHARS"]
