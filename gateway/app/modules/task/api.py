from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request

from app.modules.task.schema import TaskCreate, TaskResponse
from app.modules.task.service import TaskExecutionError, TaskService

router = APIRouter(tags=["tasks"])


def get_task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Task service is not initialized")
    return cast(TaskService, service)


def _current_user_id(request: Request) -> str | None:
    # /tasks 对扩展保持匿名可用:有登录 cookie 就用其简历,没有就回退本地文件。
    auth_service = getattr(request.app.state, "auth_service", None)
    if auth_service is None:
        return None
    user = auth_service.get_current_user(request.session)
    return user.user_id if user is not None else None


@router.post("/tasks", response_model=TaskResponse)
def create_task(task: TaskCreate, request: Request) -> TaskResponse:
    service = get_task_service(request)
    try:
        return service.run(task, user_id=_current_user_id(request))
    except ValueError as exc:
        # 未知 agent / 登录用户无可用简历 -> 客户端可纠正。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskExecutionError as exc:
        # agent 执行失败(已落 failed 记录)。
        raise HTTPException(status_code=502, detail=str(exc)) from exc
