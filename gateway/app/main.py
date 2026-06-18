import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.job_match import JobMatchAgent
from app.agents.summary_page import SummaryPageAgent
from app.config import settings
from app.core import (
    CookieSessionMiddleware,
    close_database_resources,
    create_database_resources,
)
from app.modules.auth import (
    AuthService,
    ExtensionTokenRepository,
    ExtensionTokenService,
    UserRepository,
)
from app.modules.auth.api import router as auth_router
from app.modules.resume import ResumeRepository, ResumeService, create_storage_provider
from app.modules.resume.api import router as resume_router
from app.modules.task.api import router as task_router
from app.modules.task.repo import TaskRepository
from app.modules.task.service import TaskService

# Configure our own logger so task activity prints to the terminal regardless of
# uvicorn's logging setup.
logger = logging.getLogger("agent_bridge")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        # 末尾的 %(pathname)s:%(lineno)d 是日志调用处的绝对路径+行号,
        # 终端/IDE(如 VS Code)里可点击直接跳转到打印日志的源码位置。
        logging.Formatter(
            "%(asctime)s [agent-bridge] %(levelname)s %(message)s  (%(pathname)s:%(lineno)d)"
        )
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_agent_opts: dict[str, Any] = dict(
    api_key=settings.openai_api_key or None,
    base_url=settings.openai_base_url or None,
    model=settings.model,
    model_long=settings.model_long or None,
    route_threshold_chars=settings.route_threshold_chars,
)
agents = {
    "summary_page": SummaryPageAgent(**_agent_opts),
    "job_match": JobMatchAgent(**_agent_opts),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建库（默认 SQLite，自动建表）。无 DATABASE_URL 时各 repo 为 None，
    # 登录/简历接口会明确报错，任务摘要等无状态能力仍可用（任务指标不落库）。
    db_resources = create_database_resources(settings)
    session_factory = db_resources.session_factory

    user_repository = UserRepository(session_factory) if session_factory is not None else None
    extension_token_repository = (
        ExtensionTokenRepository(session_factory) if session_factory is not None else None
    )
    resume_repository = ResumeRepository(session_factory) if session_factory is not None else None
    task_repository = TaskRepository(session_factory) if session_factory is not None else None

    resume_service = ResumeService(
        settings=settings,
        storage=create_storage_provider(settings),
        repository=resume_repository,
    )

    app.state.settings = settings
    app.state.db_resources = db_resources
    app.state.auth_service = AuthService(settings=settings, repository=user_repository)
    app.state.extension_token_service = ExtensionTokenService(
        repository=extension_token_repository,
        ttl_seconds=settings.extension_token_ttl_seconds,
    )
    app.state.resume_service = resume_service
    app.state.task_service = TaskService(
        agents=agents,
        repository=task_repository,
        resume_service=resume_service,
        default_model=settings.model,
        rate_limit_max=settings.task_rate_limit_max,
        rate_limit_window_seconds=settings.task_rate_limit_window_seconds,
    )
    try:
        yield
    finally:
        close_database_resources(db_resources)


app = FastAPI(title="Agent Bridge Gateway", lifespan=lifespan)

# 登录态 cookie（auth 模块用 request.session 读写）。
app.add_middleware(
    CookieSessionMiddleware,
    secret_key=settings.auth_session_secret,
    same_site="lax",
    https_only=settings.auth_cookie_secure,
)

# CORS:简历管理前端走带 cookie 的跨域请求(allow_credentials),所以必须回显具体
# Origin 而非 "*"。浏览器扩展通过 host_permissions 直连 /tasks,不受 CORS 约束。
_frontend = urlsplit(settings.auth_frontend_redirect_url)
_frontend_origin = f"{_frontend.scheme}://{_frontend.netloc}" if _frontend.netloc else ""
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in {_frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"} if o],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(resume_router)
app.include_router(task_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
