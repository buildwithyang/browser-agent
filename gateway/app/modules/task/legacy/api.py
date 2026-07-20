from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.modules.task.protocol import (
    DEFAULT_EXTENSION_UPDATE_URL,
    upgrade_required_response,
)

router = APIRouter(tags=["tasks-legacy"])


@router.post("/tasks", deprecated=True)
def create_legacy_task(request: Request) -> JSONResponse:
    """Return the shared upgrade response without declaring or reading a body."""

    settings = getattr(request.app.state, "settings", None)
    update_url = getattr(
        settings,
        "extension_update_url",
        DEFAULT_EXTENSION_UPDATE_URL,
    )
    return upgrade_required_response(update_url)
