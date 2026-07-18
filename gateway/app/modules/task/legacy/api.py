from fastapi import APIRouter, HTTPException, Request

from app.modules.task.api import _map_error, _user_id, get_task_service
from app.modules.task.legacy.adapter import (
    from_quick_response,
    from_task_response,
    is_quick_request,
    to_quick_request,
    to_task_request,
)
from app.modules.task.legacy.schema import LegacyTaskRequest, LegacyTaskResponse
from app.modules.task.service import RateLimitError, TaskExecutionError

router = APIRouter(tags=["tasks-legacy"])


@router.post("/tasks", response_model=LegacyTaskResponse, deprecated=True)
def create_legacy_task(task: LegacyTaskRequest, request: Request) -> LegacyTaskResponse:
    service = get_task_service(request)
    try:
        user_id = _user_id(request)
        if is_quick_request(task):
            return from_quick_response(
                service.quick_insight(to_quick_request(task), user_id=user_id)
            )
        return from_task_response(service.execute(to_task_request(task), user_id=user_id))
    except (RateLimitError, ValueError, TaskExecutionError) as exc:
        raise _map_error(exc) from exc
