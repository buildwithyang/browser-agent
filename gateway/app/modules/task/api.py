from __future__ import annotations

from typing import AsyncIterator, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.modules.auth.identity import resolve_user_id
from app.modules.task.schema import (
    QuickInsightRequest,
    QuickInsightResponse,
    WorkspaceRequest,
)
from app.modules.task.service import RateLimitError, TaskExecutionError, TaskService
from app.modules.task.stream_schema import encode_stream_event

router = APIRouter(tags=["tasks"])


def get_task_service(request: Request) -> TaskService:
    """Resolve the application-scoped TaskService dependency."""

    service = getattr(request.app.state, "task_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Task service is not initialized")
    return cast(TaskService, service)


def _user_id(request: Request) -> str | None:
    """Resolve request identity and enforce managed-mode authentication."""

    user_id = resolve_user_id(request)
    settings = getattr(request.app.state, "settings", None)
    if getattr(settings, "require_auth", False) and user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _map_error(exc: Exception) -> HTTPException:
    """Map service-layer failures to the task API HTTP contract."""

    if isinstance(exc, RateLimitError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.post("/tasks/quick-insight", response_model=QuickInsightResponse)
def create_quick_insight(
    task: QuickInsightRequest, request: Request
) -> QuickInsightResponse:
    """Produce a fast page insight and its Workspace descriptor."""

    service = get_task_service(request)
    try:
        return service.quick_insight(task, user_id=_user_id(request))
    except (RateLimitError, ValueError, TaskExecutionError) as exc:
        raise _map_error(exc) from exc


@router.post("/tasks/workspace", response_class=StreamingResponse)
async def create_workspace_task(
    task: WorkspaceRequest,
    request: Request,
) -> StreamingResponse:
    """Stream one stateless Workspace transition as NDJSON."""

    service = get_task_service(request)
    user_id = _user_id(request)
    try:
        prepared = service.prepare_workspace_stream(task, user_id=user_id)
    except Exception as exc:
        raise _map_error(exc) from exc

    async def body() -> AsyncIterator[bytes]:
        """Encode service events and stop work after client disconnect."""

        events = service.stream_workspace(prepared)
        try:
            async for event in events:
                if await request.is_disconnected():
                    break
                yield encode_stream_event(event)
        finally:
            await events.aclose()

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
