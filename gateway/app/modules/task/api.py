from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request

from app.modules.auth.identity import resolve_user_id
from app.modules.task.schema import TaskCreate, TaskResponse
from app.modules.task.service import RateLimitError, TaskExecutionError, TaskService

router = APIRouter(tags=["tasks"])


def get_task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Task service is not initialized")
    return cast(TaskService, service)


@router.post("/tasks", response_model=TaskResponse)
def create_task(task: TaskCreate, request: Request) -> TaskResponse:
    service = get_task_service(request)
    # 先 bearer 后 cookie 解析身份;扩展跨站发不出 cookie,走 Authorization: Bearer。
    user_id = resolve_user_id(request)

    settings = getattr(request.app.state, "settings", None)
    if getattr(settings, "require_auth", False) and user_id is None:
        # 托管平台:/tasks 不接受匿名调用。
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        return service.run(task, user_id=user_id)
    except RateLimitError as exc:
        # 用户超出限流窗口配额。
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        # 未知 agent / 登录用户无可用简历 -> 客户端可纠正。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskExecutionError as exc:
        # agent 执行失败(已落 failed 记录)。
        raise HTTPException(status_code=502, detail=str(exc)) from exc
