from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Callable, Generic, NoReturn, TypeVar

import anyio
from pydantic import BaseModel, TypeAdapter

from app.agents.base import (
    AgentContext,
    AgentExecution,
    QuickInsightAgent,
    RegisteredAgent,
    StreamingWorkspaceAgent,
    WorkspaceAgent,
    WorkspaceAgentContext,
    WorkspaceContextPreparer,
)
from app.agents.stream import (
    AgentCompleted,
    AgentDelta,
    AgentStatus,
    closing_if_supported,
)
from app.modules.resume import ResumeService
from app.modules.task.repo import TaskRepository
from app.modules.task.router import normalize_resource_url, route_browser_task
from app.modules.task.schema import (
    ARTIFACT_VERSION_MAX,
    ActionId,
    AgentName,
    Artifact,
    Artifacts,
    ArtifactType,
    Attachment,
    ChatResult,
    CreateArtifactResult,
    ExecutionMeta,
    HistoryMessage,
    Insight,
    PageContext,
    QuickInsightRequest,
    QuickInsightResponse,
    ReplyResult,
    TaskRecordData,
    UpdateArtifactResult,
    UserMessageWorkspaceRequest,
    WorkspaceDescriptor,
    WorkspaceRequest,
    WorkspaceResponse,
)
from app.modules.task.stream_schema import (
    WorkspaceCompletedEvent,
    WorkspaceDeltaEvent,
    WorkspaceFailedEvent,
    WorkspaceStartedEvent,
    WorkspaceStatusEvent,
    WorkspaceStreamEvent,
    WorkspaceStreamStage,
)

logger = logging.getLogger("agent_bridge")
ContentT = TypeVar("ContentT", Insight, ChatResult)
CV_PREVIEW_URL = "https://browser.buildwithyang.com"
_CHAT_RESULT_ADAPTER = TypeAdapter(ChatResult)


@dataclass(frozen=True)
class _WorkspaceTransitionIdentity:
    """Immutable IDs and UTC time allocated after one valid Agent execution."""

    created_at: datetime
    user_message_id: uuid.UUID | None
    assistant_message_id: uuid.UUID
    artifact_id: uuid.UUID | None
    attachment_id: uuid.UUID | None


@dataclass(frozen=True)
class _StagedAgentOperation(Generic[ContentT]):
    """A timed Agent outcome whose completed metric is not yet committed."""

    request: PageContext
    agent_name: AgentName
    user_id: str | None
    record_id: uuid.UUID
    execution: AgentExecution[ContentT]
    meta: ExecutionMeta


@dataclass(frozen=True)
class PreparedWorkspaceStream:
    """Validated dependencies for one stateless Workspace event stream."""

    request: WorkspaceRequest
    resource_url: str
    agent_name: AgentName
    agent: StreamingWorkspaceAgent
    context: WorkspaceAgentContext
    user_id: str | None
    started_at: datetime


class _AgentStreamContractError(ValueError):
    """Raised when an Agent violates the Workspace stream lifecycle."""


@dataclass
class _AgentStreamLifecycle:
    """Validate legal Agent progress using an explicit per-request state machine."""

    routing_seen: bool = False
    generation_stage: WorkspaceStreamStage | None = None
    artifact_type: ArtifactType | None = None
    finalizing: bool = False

    def accept_status(self, event: AgentStatus) -> None:
        """Advance one legal status without allowing regressions or mode changes."""

        try:
            stage = WorkspaceStreamStage(event.stage)
        except ValueError as exc:
            raise _AgentStreamContractError("Agent emitted an unknown status") from exc

        if stage is WorkspaceStreamStage.ROUTING:
            if self.routing_seen or self.generation_stage is not None or self.finalizing:
                raise _AgentStreamContractError("Agent routing status is out of order")
            if event.artifact_type is not None:
                raise _AgentStreamContractError("Agent routing status has artifact metadata")
            self.routing_seen = True
            return

        if stage in {
            WorkspaceStreamStage.GENERATING_REPLY,
            WorkspaceStreamStage.GENERATING_ARTIFACT,
        }:
            if self.generation_stage is not None or self.finalizing:
                raise _AgentStreamContractError("Agent generation status is out of order")
            is_artifact = stage is WorkspaceStreamStage.GENERATING_ARTIFACT
            if is_artifact != (event.artifact_type is not None):
                raise _AgentStreamContractError("Agent generation metadata is invalid")
            self.generation_stage = stage
            self.artifact_type = event.artifact_type
            return

        if self.generation_stage is None or self.finalizing:
            raise _AgentStreamContractError("Agent finalizing status is out of order")
        if event.artifact_type is not None:
            raise _AgentStreamContractError("Agent finalizing status has artifact metadata")
        self.finalizing = True

    def accept_delta(self) -> None:
        """Allow visible Markdown only during ordinary reply generation."""

        if (
            self.generation_stage is not WorkspaceStreamStage.GENERATING_REPLY
            or self.finalizing
        ):
            raise _AgentStreamContractError("Agent delta is invalid for the active mode")

    def accept_completed(self, execution: AgentExecution[ChatResult]) -> None:
        """Cross-check terminal result type against the selected generation mode."""

        if not self.finalizing:
            raise _AgentStreamContractError("Agent completed before finalizing")
        result = execution.content
        if self.generation_stage is WorkspaceStreamStage.GENERATING_REPLY:
            if not isinstance(result, ReplyResult):
                raise _AgentStreamContractError("Reply stream returned an Artifact")
            return
        if not isinstance(result, CreateArtifactResult | UpdateArtifactResult):
            raise _AgentStreamContractError("Artifact stream returned a reply")
        if result.artifact_type is not self.artifact_type:
            raise _AgentStreamContractError("Artifact stream changed Artifact type")


def _artifact_for_type(
    artifacts: Artifacts,
    artifact_type: ArtifactType,
) -> Artifact | None:
    """Return the latest Artifact from its fixed type slot."""

    return artifacts.cv if artifact_type is ArtifactType.CV else artifacts.cover_letter


def _validate_workspace_transition(
    request: WorkspaceRequest,
    result: object,
) -> ChatResult:
    """Validate one Agent result and its create/update precondition before allocation."""

    if isinstance(result, ReplyResult):
        return result
    if not isinstance(result, CreateArtifactResult | UpdateArtifactResult):
        raise ValueError("Workspace Agent returned an invalid ChatResult")

    existing = _artifact_for_type(request.artifacts, result.artifact_type)
    if isinstance(result, CreateArtifactResult) and existing is not None:
        raise ValueError("create_artifact requires an empty same-type Artifact slot")
    if isinstance(result, UpdateArtifactResult):
        if existing is None:
            raise ValueError("update_artifact requires an existing same-type Artifact")
        if existing.version >= ARTIFACT_VERSION_MAX:
            raise ValueError("Artifact version cannot be incremented")
    if (
        result.artifact_type is ArtifactType.COVER_LETTER
        and len(result.draft) == 0
    ):
        raise ValueError("Cover Letter Attachment content must not be empty")
    return result


def _validated_workspace_execution(
    request: WorkspaceRequest,
    execution: AgentExecution[ChatResult],
) -> AgentExecution[ChatResult]:
    """Fully revalidate Agent output before checking transition preconditions."""

    payload = (
        execution.content.model_dump(mode="python")
        if isinstance(execution.content, BaseModel)
        else execution.content
    )
    result = _CHAT_RESULT_ADAPTER.validate_python(payload)
    _validate_workspace_transition(request, result)
    return AgentExecution(
        content=result,
        raw_result=execution.raw_result,
        prompt=execution.prompt,
        model=execution.model,
    )


def _reduce_workspace_state(
    request: WorkspaceRequest,
    result: ChatResult,
    *,
    identity: _WorkspaceTransitionIdentity,
) -> tuple[list[HistoryMessage], Artifacts]:
    """Return one complete next state without mutating the validated prior state."""

    histories = list(request.histories)
    if isinstance(request, UserMessageWorkspaceRequest):
        if identity.user_message_id is None:
            raise ValueError("user-message transition identity is incomplete")
        histories.append(
            HistoryMessage(
                id=identity.user_message_id,
                role="user",
                content=request.message,
                action_id=request.action_id,
                created_at=identity.created_at,
            )
        )

    artifacts = request.artifacts
    attachment: Attachment | None = None
    if isinstance(result, CreateArtifactResult | UpdateArtifactResult):
        existing = _artifact_for_type(artifacts, result.artifact_type)
        if identity.attachment_id is None:
            raise ValueError("artifact transition identity is incomplete")
        if existing is None and identity.artifact_id is None:
            raise ValueError("create transition identity is incomplete")
        artifact_id = identity.artifact_id if existing is None else existing.id
        if artifact_id is None:
            raise ValueError("Artifact identity is missing")
        version = 1 if existing is None else existing.version + 1
        attachment = Attachment(
            id=identity.attachment_id,
            artifact_id=artifact_id,
            version=version,
            type=result.artifact_type,
            title=result.title,
            content=(
                CV_PREVIEW_URL
                if result.artifact_type is ArtifactType.CV
                else result.draft
            ),
        )
        artifact = Artifact(
            id=artifact_id,
            type=result.artifact_type,
            version=version,
            title=result.title,
            draft=result.draft,
            attachment=attachment,
        )
        artifacts = Artifacts(
            cv=artifact if result.artifact_type is ArtifactType.CV else artifacts.cv,
            cover_letter=(
                artifact
                if result.artifact_type is ArtifactType.COVER_LETTER
                else artifacts.cover_letter
            ),
        )

    histories.append(
        HistoryMessage(
            id=identity.assistant_message_id,
            role="assistant",
            content=result.markdown,
            action_id=request.action_id,
            created_at=identity.created_at,
            attachments=[attachment] if attachment is not None else [],
        )
    )
    return histories, artifacts


def _allocate_workspace_transition_identity(
    request: WorkspaceRequest,
    result: ChatResult,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> _WorkspaceTransitionIdentity:
    """Allocate the exact immutable identity set required by a valid transition."""

    created_at = clock()
    if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
        raise ValueError("Workspace transition time must be UTC")
    user_message_id = new_id() if isinstance(request, UserMessageWorkspaceRequest) else None
    creates_artifact = isinstance(result, CreateArtifactResult)
    changes_artifact = isinstance(result, CreateArtifactResult | UpdateArtifactResult)
    artifact_id = new_id() if creates_artifact else None
    attachment_id = new_id() if changes_artifact else None
    assistant_message_id = new_id()
    return _WorkspaceTransitionIdentity(
        created_at=created_at,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        artifact_id=artifact_id,
        attachment_id=attachment_id,
    )


class TaskExecutionError(RuntimeError):
    """agent 执行失败:已落库 failed 记录,api 应映射为 502。"""


class RateLimitError(RuntimeError):
    """用户在限流窗口内超额:api 应映射为 429。"""


class TaskService:
    """任务请求生命周期:agent 分发 -> (job_match)解析用户简历 -> 执行 -> 落库。

    无 DB 时跳过持久化,摘要等无状态能力照常可用。
    """

    def __init__(
        self,
        *,
        agents: dict[AgentName, RegisteredAgent],
        repository: TaskRepository | None,
        resume_service: ResumeService | None,
        default_model: str,
        rate_limit_max: int = 20,
        rate_limit_window_seconds: int = 86400,
        workspace_id_factory: Callable[[], uuid.UUID] | None = None,
        workspace_clock: Callable[[], datetime] | None = None,
        perf_counter: Callable[[], float] | None = None,
    ) -> None:
        """Inject stateless Agents, operational stores, limits, and testable clocks."""

        self._agents = agents
        self._repository = repository
        self._resume_service = resume_service
        self._default_model = default_model
        self._rate_limit_max = rate_limit_max
        self._rate_limit_window_seconds = rate_limit_window_seconds
        self._workspace_id_factory = workspace_id_factory or uuid.uuid4
        self._workspace_clock = workspace_clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._perf_counter = perf_counter or time.perf_counter

    def quick_insight(
        self,
        request: QuickInsightRequest,
        *,
        user_id: str | None,
    ) -> QuickInsightResponse:
        """Execute Quick Insight and describe the page's stable Workspace."""

        resource_url = normalize_resource_url(request.url)
        routed, agent = self._resolve_agent(request)
        execution, meta, ctx = self._execute_agent(
            request,
            agent_name=routed,
            agent=agent,
            user_id=user_id,
            operation=lambda ctx: agent.quick_insight(ctx),
        )
        return QuickInsightResponse(
            request=request,
            insight=execution.content,
            actions=agent.available_actions(ctx),
            workspace=WorkspaceDescriptor(
                resource_url=resource_url,
                default_action_id=(
                    ActionId.ANALYZE
                    if routed is AgentName.JOB_MATCH
                    else ActionId.ASK_MORE
                ),
            ),
            meta=meta,
        )

    def workspace(
        self,
        request: WorkspaceRequest,
        *,
        user_id: str | None,
    ) -> WorkspaceResponse:
        """Execute one v2 Agent call and atomically reduce its complete next state."""

        resource_url = normalize_resource_url(request.url)
        if request.resource_url != resource_url:
            raise ValueError("resourceUrl does not match normalized url")

        routed, agent = self._resolve_agent(request)
        outcome, _ = self._execute_workspace_agent(
            request,
            agent_name=routed,
            agent=agent,
            user_id=user_id,
        )
        try:
            execution = _validated_workspace_execution(request, outcome.execution)
            # State identity is allocated only after complete ChatResult
            # revalidation and create/update precondition checks succeed.
            identity = _allocate_workspace_transition_identity(
                request,
                execution.content,
                new_id=self._workspace_id_factory,
                clock=self._workspace_clock,
            )
            histories, artifacts = _reduce_workspace_state(
                request,
                execution.content,
                identity=identity,
            )
            response = WorkspaceResponse(
                resource_url=resource_url,
                selected_action_id=request.action_id,
                result_type=execution.content.type,
                histories=histories,
                artifacts=artifacts,
                meta=outcome.meta,
            )
        except Exception as exc:
            self._fail_staged_agent_operation(outcome, exc)

        self._complete_staged_agent_operation(outcome)
        return response

    def prepare_workspace_stream(
        self,
        request: WorkspaceRequest,
        *,
        user_id: str | None,
    ) -> PreparedWorkspaceStream:
        """Validate all ordinary HTTP failure boundaries before streaming starts."""

        resource_url = normalize_resource_url(request.url)
        if request.resource_url != resource_url:
            raise ValueError("resourceUrl does not match normalized url")

        agent_name, agent = self._resolve_agent(request)
        if not isinstance(agent, StreamingWorkspaceAgent):
            raise ValueError(f"Agent does not support Workspace streaming: {agent_name}")
        self._enforce_rate_limit(user_id)
        resume_text = self._resolve_cv_text(user_id) if agent.requires_resume else None
        context = self._prepare_workspace_context(
            request,
            agent=agent,
            resume_text=resume_text,
        )
        return PreparedWorkspaceStream(
            request=request,
            resource_url=resource_url,
            agent_name=agent_name,
            agent=agent,
            context=context,
            user_id=user_id,
            started_at=datetime.now(timezone.utc),
        )

    async def stream_workspace(
        self,
        prepared: PreparedWorkspaceStream,
    ) -> AsyncIterator[WorkspaceStreamEvent]:
        """Map one Agent stream and atomically emit a single terminal wire event."""

        request = prepared.request
        operation_id = request.operation_id
        record_id = uuid.uuid4()
        sequence = 0
        t0 = self._perf_counter()
        terminal_recorded = False
        lifecycle = _AgentStreamLifecycle()

        def elapsed_ms() -> int:
            """Return elapsed stream time in whole milliseconds."""

            return int((self._perf_counter() - t0) * 1000)

        async def persist_failure(code: str, duration_ms: int) -> None:
            """Persist bounded failure metrics without blocking the ASGI event loop."""

            await anyio.to_thread.run_sync(
                self._persist,
                record_id.hex,
                request,
                prepared.agent_name,
                prepared.user_id,
                self._default_model,
                "failed",
                0,
                0,
                duration_ms,
                code,
            )
            logger.warning(
                "workspace task failed agent=%s code=%s duration_ms=%d",
                prepared.agent_name,
                code,
                duration_ms,
            )

        try:
            yield WorkspaceStartedEvent(
                operation_id=operation_id,
                sequence=sequence,
                created_at=prepared.started_at,
            )
            sequence += 1

            agent_events = prepared.agent.stream_chat(prepared.context)
            async with closing_if_supported(agent_events) as owned_events:
                # Deltas remain transient; only AgentCompleted may enter the reducer.
                async for event in owned_events:
                    if isinstance(event, AgentStatus):
                        lifecycle.accept_status(event)
                        yield WorkspaceStatusEvent(
                            operation_id=operation_id,
                            sequence=sequence,
                            stage=event.stage,
                            artifact_type=event.artifact_type,
                        )
                        sequence += 1
                        continue
                    if isinstance(event, AgentDelta):
                        lifecycle.accept_delta()
                        yield WorkspaceDeltaEvent(
                            operation_id=operation_id,
                            sequence=sequence,
                            text=event.text,
                        )
                        sequence += 1
                        continue
                    if not isinstance(event, AgentCompleted):
                        raise TypeError("Workspace Agent yielded an unsupported event")
                    lifecycle.accept_completed(event.execution)

                    # Model output validation is distinct from Gateway-owned finalization.
                    try:
                        execution = _validated_workspace_execution(
                            request,
                            event.execution,
                        )
                    except (ValueError, TypeError):
                        duration_ms = elapsed_ms()
                        await persist_failure("invalid_model_output", duration_ms)
                        terminal_recorded = True
                        yield WorkspaceFailedEvent(
                            operation_id=operation_id,
                            sequence=sequence,
                            code="invalid_model_output",
                            message="Workspace model output was invalid.",
                            recoverable=True,
                        )
                        return

                    # Allocate and validate the canonical next state as one atomic step.
                    try:
                        identity = _allocate_workspace_transition_identity(
                            request,
                            execution.content,
                            new_id=self._workspace_id_factory,
                            clock=self._workspace_clock,
                        )
                        histories, artifacts = _reduce_workspace_state(
                            request,
                            execution.content,
                            identity=identity,
                        )
                        duration_ms = elapsed_ms()
                        finished_at = datetime.now(timezone.utc)
                        meta = ExecutionMeta(
                            id=record_id,
                            created_at=prepared.started_at,
                            status="completed",
                            input_chars=len(execution.prompt),
                            model=execution.model,
                            started_at=prepared.started_at,
                            finished_at=finished_at,
                            duration_ms=duration_ms,
                        )
                        response = WorkspaceResponse(
                            resource_url=prepared.resource_url,
                            selected_action_id=request.action_id,
                            result_type=execution.content.type,
                            histories=histories,
                            artifacts=artifacts,
                            meta=meta,
                        )
                    except Exception:
                        duration_ms = elapsed_ms()
                        await persist_failure("internal_error", duration_ms)
                        terminal_recorded = True
                        yield WorkspaceFailedEvent(
                            operation_id=operation_id,
                            sequence=sequence,
                            code="internal_error",
                            message="Workspace finalization failed.",
                            recoverable=True,
                        )
                        return

                    outcome = _StagedAgentOperation(
                        request=request,
                        agent_name=prepared.agent_name,
                        user_id=prepared.user_id,
                        record_id=record_id,
                        execution=execution,
                        meta=meta,
                    )
                    yield WorkspaceCompletedEvent(
                        operation_id=operation_id,
                        sequence=sequence,
                        response=response,
                    )
                    # Resuming after the terminal yield is the ASGI boundary's
                    # acknowledgement that sending the completed chunk did not cancel.
                    terminal_recorded = True
                    await anyio.to_thread.run_sync(
                        self._complete_staged_agent_operation,
                        outcome,
                    )
                    return

            duration_ms = elapsed_ms()
            await persist_failure("stream_interrupted", duration_ms)
            terminal_recorded = True
            yield WorkspaceFailedEvent(
                operation_id=operation_id,
                sequence=sequence,
                code="stream_interrupted",
                message="Workspace stream ended before completion.",
                recoverable=True,
            )
        except _AgentStreamContractError:
            if terminal_recorded:
                logger.warning(
                    "workspace stream contract cleanup failed agent=%s",
                    prepared.agent_name,
                )
                return
            duration_ms = elapsed_ms()
            await persist_failure("invalid_model_output", duration_ms)
            terminal_recorded = True
            yield WorkspaceFailedEvent(
                operation_id=operation_id,
                sequence=sequence,
                code="invalid_model_output",
                message="Workspace model output was invalid.",
                recoverable=True,
            )
        except Exception:
            if terminal_recorded:
                logger.warning(
                    "workspace stream cleanup failed agent=%s",
                    prepared.agent_name,
                )
                return
            duration_ms = elapsed_ms()
            await persist_failure("model_error", duration_ms)
            terminal_recorded = True
            yield WorkspaceFailedEvent(
                operation_id=operation_id,
                sequence=sequence,
                code="model_error",
                message="Workspace model generation failed.",
                recoverable=True,
            )
        finally:
            # Client disconnect closes this generator; record no partial text or Artifact.
            if not terminal_recorded:
                await persist_failure("stream_interrupted", elapsed_ms())

    def _resolve_agent(
        self,
        request: PageContext,
    ) -> tuple[AgentName, RegisteredAgent]:
        """Resolve a public page request to one internal stateless Agent."""

        routed = route_browser_task(request)
        agent = self._agents.get(routed)
        if agent is None:
            raise ValueError(f"Unsupported agent: {routed}")
        return routed, agent

    @staticmethod
    def _prepare_workspace_context(
        request: WorkspaceRequest,
        *,
        agent: RegisteredAgent,
        resume_text: str | None,
    ) -> WorkspaceAgentContext:
        """Resolve optional Agent-owned dependencies before a Workspace operation starts."""

        context = WorkspaceAgentContext(request=request, resume_text=resume_text)
        if isinstance(agent, WorkspaceContextPreparer):
            return agent.prepare_workspace_context(context)
        return context

    def _execute_agent(
        self,
        request: PageContext,
        *,
        agent_name: AgentName,
        agent: QuickInsightAgent,
        user_id: str | None,
        operation: Callable[[AgentContext], AgentExecution[ContentT]],
    ) -> tuple[AgentExecution[ContentT], ExecutionMeta, AgentContext]:
        """Run one validated Agent call and capture metrics consistently."""

        self._enforce_rate_limit(user_id)
        logger.info("task received agent=%s url=%s", agent_name, request.url)

        resume_text = self._resolve_cv_text(user_id) if agent.requires_resume else None
        ctx = AgentContext(request=request, resume_text=resume_text)
        execution, meta = self._run_agent_operation(
            request,
            agent_name=agent_name,
            user_id=user_id,
            operation=lambda: operation(ctx),
        )
        return execution, meta, ctx

    def _execute_workspace_agent(
        self,
        request: WorkspaceRequest,
        *,
        agent_name: AgentName,
        agent: RegisteredAgent,
        user_id: str | None,
    ) -> tuple[_StagedAgentOperation[ChatResult], WorkspaceAgentContext]:
        """Prepare dependencies and stage one timed Workspace Agent outcome."""

        if not isinstance(agent, WorkspaceAgent):
            raise ValueError(f"Agent does not support Workspace chat: {agent_name}")
        self._enforce_rate_limit(user_id)
        logger.info("task received agent=%s url=%s", agent_name, request.url)

        resume_text = self._resolve_cv_text(user_id) if agent.requires_resume else None
        ctx = self._prepare_workspace_context(
            request,
            agent=agent,
            resume_text=resume_text,
        )
        outcome = self._stage_agent_operation(
            request,
            agent_name=agent_name,
            user_id=user_id,
            operation=lambda: agent.handle_chat(ctx),
        )
        return outcome, ctx

    def _run_agent_operation(
        self,
        request: PageContext,
        *,
        agent_name: AgentName,
        user_id: str | None,
        operation: Callable[[], AgentExecution[ContentT]],
    ) -> tuple[AgentExecution[ContentT], ExecutionMeta]:
        """Time one complete Agent operation and persist operational metrics."""

        outcome = self._stage_agent_operation(
            request,
            agent_name=agent_name,
            user_id=user_id,
            operation=operation,
        )
        self._complete_staged_agent_operation(outcome)
        return outcome.execution, outcome.meta

    def _stage_agent_operation(
        self,
        request: PageContext,
        *,
        agent_name: AgentName,
        user_id: str | None,
        operation: Callable[[], AgentExecution[ContentT]],
    ) -> _StagedAgentOperation[ContentT]:
        """Time an Agent call without committing its completed metric yet."""

        rid = uuid.uuid4()
        started_at = datetime.now(timezone.utc)
        t0 = self._perf_counter()
        model = self._default_model
        prompt = ""
        try:
            execution = operation()
            prompt = execution.prompt
            model = execution.model
            duration_ms = int((self._perf_counter() - t0) * 1000)
            meta = ExecutionMeta(
                id=rid,
                created_at=started_at,
                status="completed",
                input_chars=len(prompt),
                model=model,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
            )
            return _StagedAgentOperation(
                request=request,
                agent_name=agent_name,
                user_id=user_id,
                record_id=rid,
                execution=execution,
                meta=meta,
            )
        except Exception as exc:
            duration_ms = int((self._perf_counter() - t0) * 1000)
            self._persist(
                rid.hex, request, agent_name, user_id, model, "failed",
                len(prompt), 0, duration_ms, str(exc)[:512],
            )
            logger.exception(
                "task failed agent=%s input=%.1fk duration_ms=%d",
                agent_name, len(prompt) / 1000, duration_ms,
            )
            raise TaskExecutionError(str(exc)) from exc

    def _complete_staged_agent_operation(
        self,
        outcome: _StagedAgentOperation[ContentT],
    ) -> None:
        """Commit completed metrics only after all caller finalization succeeds."""

        execution = outcome.execution
        duration_ms = outcome.meta.duration_ms
        self._persist(
            outcome.record_id.hex,
            outcome.request,
            outcome.agent_name,
            outcome.user_id,
            execution.model,
            "completed",
            len(execution.prompt),
            len(execution.raw_result),
            duration_ms,
            "",
            prompt=execution.prompt,
            result=execution.raw_result,
            include_private_details=True,
        )
        logger.info(
            "task completed agent=%s model=%s input=%.1fk duration_ms=%d chars=%d",
            outcome.agent_name,
            execution.model,
            len(execution.prompt) / 1000,
            duration_ms or 0,
            len(execution.raw_result),
        )

    def _fail_staged_agent_operation(
        self,
        outcome: _StagedAgentOperation[ContentT],
        exc: Exception,
    ) -> NoReturn:
        """Commit one failed metric for a staged outcome and raise the service error."""

        execution = outcome.execution
        self._persist(
            outcome.record_id.hex,
            outcome.request,
            outcome.agent_name,
            outcome.user_id,
            execution.model,
            "failed",
            len(execution.prompt),
            0,
            outcome.meta.duration_ms,
            str(exc)[:512],
        )
        logger.exception(
            "task failed agent=%s input=%.1fk duration_ms=%d",
            outcome.agent_name,
            len(execution.prompt) / 1000,
            outcome.meta.duration_ms or 0,
        )
        raise TaskExecutionError(str(exc)) from exc

    def recent_for_user(self, *, user_id: str, limit: int = 50) -> list[TaskRecordData]:
        """Return recent operational task records when persistence is configured."""

        if self._repository is None:
            return []
        return self._repository.list_recent(user_id=user_id, limit=limit)

    def _enforce_rate_limit(self, user_id: str | None) -> None:
        """Reject an identified user whose configured task quota is exhausted."""

        # 仅对已识别用户限流;匿名(自部署)不限。0 = 关闭。
        if user_id is None or self._repository is None or self._rate_limit_max <= 0:
            return
        since = datetime.now(timezone.utc) - timedelta(seconds=self._rate_limit_window_seconds)
        used = self._repository.count_since(user_id=user_id, since=since)
        if used >= self._rate_limit_max:
            raise RateLimitError(
                f"已达使用上限({self._rate_limit_max} 次 / {self._rate_limit_window_seconds}s),请稍后再试。"
            )

    def _resolve_cv_text(self, user_id: str | None) -> str | None:
        """Resolve the current user's active CV text for a request-scoped Agent context."""

        if user_id is None:
            return None
        if self._resume_service is None:
            raise ValueError("尚未设置可用简历,请先在简历管理页上传并解析成功后再试。")
        text = self._resume_service.active_resume_text(user_id=user_id)
        if not text:
            raise ValueError("尚未设置可用简历,请先在简历管理页上传并解析成功后再试。")
        return text

    def _persist(
        self,
        record_id: str,
        task: PageContext,
        agent_name: AgentName,
        user_id: str | None,
        model: str,
        status: str,
        input_chars: int,
        result_chars: int,
        duration_ms: int | None,
        error: str,
        *,
        prompt: str = "",
        result: str = "",
        include_private_details: bool = False,
    ) -> None:
        """Persist metrics and only explicitly requested private task details."""

        if self._repository is None:
            return
        detail = (
            {
                "url": task.url,
                "title": task.title,
                "prompt": prompt,
                "page_text": task.page_text,
                "result": result,
            }
            if include_private_details
            else {}
        )
        try:
            self._repository.append(
                TaskRecordData(
                    id=record_id,
                    user_id=user_id,
                    agent=agent_name,
                    lang=task.lang,
                    model=model,
                    status=status,
                    input_chars=input_chars,
                    result_chars=result_chars,
                    duration_ms=duration_ms,
                    error=error,
                    created_at=datetime.now(timezone.utc),
                    **detail,
                )
            )
        except Exception:
            # 指标落库失败不影响响应；异常正文可能携带隐私，只记录关联 ID。
            logger.warning("task metrics persist failed id=%s", record_id)
