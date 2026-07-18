from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request

from app.modules.auth.identity import resolve_user_id
from app.modules.task.schema import (
    QuickInsightRequest,
    QuickInsightResponse,
    TaskRequest,
    TaskResponse,
)
from app.modules.task.service import RateLimitError, TaskExecutionError, TaskService

router = APIRouter(tags=["tasks"])


def get_task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Task service is not initialized")
    return cast(TaskService, service)


def _user_id(request: Request) -> str | None:
    user_id = resolve_user_id(request)
    settings = getattr(request.app.state, "settings", None)
    if getattr(settings, "require_auth", False) and user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RateLimitError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.post("/tasks/quick-insight", response_model=QuickInsightResponse)
def create_quick_insight(
    task: QuickInsightRequest, request: Request
) -> QuickInsightResponse:
    service = get_task_service(request)
    try:
        return service.quick_insight(task, user_id=_user_id(request))
    except (RateLimitError, ValueError, TaskExecutionError) as exc:
        raise _map_error(exc) from exc


@router.post("/tasks/current-task", response_model=TaskResponse)
def create_current_task(task: TaskRequest, request: Request) -> TaskResponse:
    service = get_task_service(request)
    try:
        return service.execute(task, user_id=_user_id(request))
    except (RateLimitError, ValueError, TaskExecutionError) as exc:
        raise _map_error(exc) from exc
