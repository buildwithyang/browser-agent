from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, TypeVar

from app.agents.base import AgentContext, AgentExecution, TaskAgent
from app.modules.resume import ResumeService
from app.modules.task.repo import TaskRepository
from app.modules.task.router import route_browser_task
from app.modules.task.schema import (
    AgentName,
    DocumentContent,
    ExecutionMeta,
    Insight,
    PageContext,
    QuickInsightRequest,
    QuickInsightResponse,
    TaskRecordData,
    TaskRequest,
    TaskResponse,
)

logger = logging.getLogger("agent_bridge")
ContentT = TypeVar("ContentT", Insight, DocumentContent)


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
        agents: dict[AgentName, TaskAgent],
        repository: TaskRepository | None,
        resume_service: ResumeService | None,
        default_model: str,
        rate_limit_max: int = 20,
        rate_limit_window_seconds: int = 86400,
    ) -> None:
        self._agents = agents
        self._repository = repository
        self._resume_service = resume_service
        self._default_model = default_model
        self._rate_limit_max = rate_limit_max
        self._rate_limit_window_seconds = rate_limit_window_seconds

    def quick_insight(
        self, request: QuickInsightRequest, *, user_id: str | None
    ) -> QuickInsightResponse:
        routed, agent = self._resolve_agent(request)
        request = request.model_copy(update={"agent": routed})
        execution, meta = self._execute_agent(
            request,
            agent=agent,
            user_id=user_id,
            operation=lambda ctx: agent.insight(ctx),
        )
        return QuickInsightResponse(
            request=request,
            insight=execution.content,
            actions=execution.actions,
            meta=meta,
        )

    def execute(self, request: TaskRequest, *, user_id: str | None) -> TaskResponse:
        routed, agent = self._resolve_agent(request)
        request = request.model_copy(update={"agent": routed})
        execution, meta = self._execute_agent(
            request,
            agent=agent,
            user_id=user_id,
            operation=lambda ctx: agent.execute(ctx),
        )
        return TaskResponse(request=request, document=execution.content, meta=meta)

    def _resolve_agent(self, request: PageContext) -> tuple[AgentName, TaskAgent]:
        routed = (
            route_browser_task(request)
            if request.agent is AgentName.BROWSER_AGENT
            else request.agent
        )
        agent = self._agents.get(routed)
        if agent is None:
            raise ValueError(f"Unsupported agent: {routed}")
        return routed, agent

    def _execute_agent(
        self,
        request: PageContext,
        *,
        agent: TaskAgent,
        user_id: str | None,
        operation: Callable[[AgentContext], AgentExecution[ContentT]],
    ) -> tuple[AgentExecution[ContentT], ExecutionMeta]:
        self._enforce_rate_limit(user_id)
        logger.info("task received agent=%s url=%s", request.agent, request.url)

        resume_text = self._resolve_cv_text(user_id) if agent.requires_resume else None
        ctx = AgentContext(request=request, resume_text=resume_text)
        # Stable contract: every agent validates explicitly; no reflection or concrete-type checks.
        agent.validate(ctx)

        rid = uuid.uuid4()
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        model = self._default_model
        prompt = ""
        try:
            execution = operation(ctx)
            prompt = execution.prompt
            model = execution.model
            result = execution.raw_result
            duration_ms = int((time.perf_counter() - t0) * 1000)
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
            self._persist(
                rid.hex, request, user_id, model, "completed",
                len(prompt), len(result), duration_ms, "",
                prompt=prompt, result=result,
            )
            logger.info(
                "task completed agent=%s model=%s input=%.1fk duration_ms=%d chars=%d",
                request.agent, model, len(prompt) / 1000, duration_ms, len(result),
            )
            return execution, meta
        except Exception as exc:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            self._persist(
                rid.hex, request, user_id, model, "failed",
                len(prompt), 0, duration_ms, str(exc)[:512],
                prompt=prompt, result="",
            )
            logger.exception(
                "task failed agent=%s input=%.1fk duration_ms=%d",
                request.agent, len(prompt) / 1000, duration_ms,
            )
            raise TaskExecutionError(str(exc)) from exc

    def recent_for_user(self, *, user_id: str, limit: int = 50) -> list[TaskRecordData]:
        if self._repository is None:
            return []
        return self._repository.list_recent(user_id=user_id, limit=limit)

    def _enforce_rate_limit(self, user_id: str | None) -> None:
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
    ) -> None:
        if self._repository is None:
            return
        detail = {
            "url": task.url,
            "title": task.title,
            "prompt": prompt,
            "page_text": task.page_text,
            "result": result,
        }
        try:
            self._repository.append(
                TaskRecordData(
                    id=record_id,
                    user_id=user_id,
                    agent=task.agent,
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
        except Exception as exc:
            # 指标落库失败不该影响用户拿到结果,记日志即可。
            logger.warning("task metrics persist failed id=%s err=%s", record_id, exc)
