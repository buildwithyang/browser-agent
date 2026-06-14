from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agents.job_match import JobMatchAgent
from app.modules.resume import ResumeService
from app.modules.task.repo import TaskRepository
from app.modules.task.schema import TaskCreate, TaskRecordData, TaskResponse
from app.render import render_markdown

logger = logging.getLogger("agent_bridge")


class TaskExecutionError(RuntimeError):
    """agent 执行失败:已落库 failed 记录,api 应映射为 502。"""


class TaskService:
    """任务请求生命周期:agent 分发 -> (job_match)解析用户简历 -> 执行 -> 落库指标。

    持久化是 metrics-only 且可选:无 DB 时跳过,摘要等无状态能力照常可用。
    """

    def __init__(
        self,
        *,
        agents: dict[str, Any],
        repository: TaskRepository | None,
        resume_service: ResumeService | None,
        default_model: str,
    ) -> None:
        self._agents = agents
        self._repository = repository
        self._resume_service = resume_service
        self._default_model = default_model

    def run(self, task: TaskCreate, *, user_id: str | None) -> TaskResponse:
        agent = self._agents.get(task.agent)
        if agent is None:
            raise ValueError(f"Unsupported agent: {task.agent}")

        logger.info("task received agent=%s url=%s", task.agent, task.url)

        # job_match 需要简历文本:按登录用户解析(无可用简历 -> ValueError 引导上传);
        # 匿名(扩展单用户)返回 None,交给 agent 回退本地简历文件。
        run_kwargs: dict[str, Any] = {}
        if isinstance(agent, JobMatchAgent):
            run_kwargs["cv_text"] = self._resolve_cv_text(user_id)

        rid = uuid.uuid4()
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        model = self._default_model
        prompt = ""
        try:
            prompt = agent.build_prompt(task, **run_kwargs)
            if hasattr(agent, "pick_model"):
                model = agent.pick_model(prompt)
            result = agent.run(task, **run_kwargs)
            duration_ms = int((time.perf_counter() - t0) * 1000)

            sections = agent.build_sections(result, task.lang) if hasattr(agent, "build_sections") else []
            if sections:
                # 给忽略 sections 的客户端留一份干净的回退 HTML。
                result_html = "".join(
                    (f"<h3>{s.title}</h3>{s.html}" if s.title else s.html) for s in sections
                )
            else:
                result_html = render_markdown(result)

            response = TaskResponse(
                id=rid,
                created_at=started_at,
                status="completed",
                request=task,
                input_chars=len(prompt),
                model=model,
                result=result,
                result_html=result_html,
                sections=sections,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
            )
            self._persist(rid.hex, task, user_id, model, "completed", len(prompt), len(result), duration_ms, "")
            logger.info(
                "task completed agent=%s model=%s input=%.1fk duration_ms=%d chars=%d",
                task.agent, model, len(prompt) / 1000, duration_ms, len(result),
            )
            return response
        except Exception as exc:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            self._persist(
                rid.hex, task, user_id, model, "failed", len(prompt), 0, duration_ms, str(exc)[:512]
            )
            logger.exception(
                "task failed agent=%s input=%.1fk duration_ms=%d",
                task.agent, len(prompt) / 1000, duration_ms,
            )
            raise TaskExecutionError(str(exc)) from exc

    def recent_for_user(self, *, user_id: str, limit: int = 50) -> list[TaskRecordData]:
        if self._repository is None:
            return []
        return self._repository.list_recent(user_id=user_id, limit=limit)

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
        task: TaskCreate,
        user_id: str | None,
        model: str,
        status: str,
        input_chars: int,
        result_chars: int,
        duration_ms: int | None,
        error: str,
    ) -> None:
        if self._repository is None:
            return
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
                )
            )
        except Exception as exc:
            # 指标落库失败不该影响用户拿到结果,记日志即可。
            logger.warning("task metrics persist failed id=%s err=%s", record_id, exc)
