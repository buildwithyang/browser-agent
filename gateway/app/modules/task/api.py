from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import cast

import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from app.modules.auth.identity import resolve_user_id
from app.modules.task.schema import (
    QuickInsightRequest,
    QuickInsightResponse,
    WorkspaceRequest,
)
from app.modules.task.service import RateLimitError, TaskExecutionError, TaskService
from app.modules.task.stream_schema import encode_stream_event

router = APIRouter(tags=["tasks"])


class _WorkspaceStreamingResponse(StreamingResponse):
    """Own and close one TaskService event stream across ASGI cancellation."""

    def __init__(
        self,
        content: AsyncIterator[bytes],
        *,
        close_stream: Callable[[], Awaitable[None]],
        media_type: str,
        headers: dict[str, str],
    ) -> None:
        """Configure streamed bytes and the request-scoped Service cleanup callback."""

        super().__init__(content, media_type=media_type, headers=headers)
        self._close_stream = close_stream

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Delegate HTTP streaming and deterministically release owned iterators."""

        try:
            await super().__call__(scope, receive, send)
        finally:
            # The ASGI send task can be cancelled while the body generator is
            # suspended at yield, so cleanup must be owned outside that generator.
            with anyio.CancelScope(shield=True):
                try:
                    await self._close_stream()
                finally:
                    close_body = getattr(self.body_iterator, "aclose", None)
                    if callable(close_body):
                        await close_body()


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
        # The repository and PDF adapters are synchronous; keep their request
        # preparation work off the shared ASGI event loop.
        prepared = await run_in_threadpool(
            service.prepare_workspace_stream,
            task,
            user_id=user_id,
        )
    except Exception as exc:
        raise _map_error(exc) from exc

    events = service.stream_workspace(prepared)

    async def body() -> AsyncIterator[bytes]:
        """Encode service events and stop work after client disconnect."""

        async for event in events:
            if await request.is_disconnected():
                break
            yield encode_stream_event(event)

    return _WorkspaceStreamingResponse(
        body(),
        close_stream=events.aclose,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
