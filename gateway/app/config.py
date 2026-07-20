import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from app.agents.model_router import ModelRouter, ModelTier
from app.modules.task.protocol import DEFAULT_EXTENSION_UPDATE_URL


def _get_env_str(name: str, default: str) -> str:
    """Return one trimmed string setting or its configured default."""

    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


def _get_env_int(name: str, default: int) -> int:
    """Return one integer setting, falling back for blank or invalid input."""

    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_float(name: str, default: float) -> float:
    """Return one float setting, falling back for blank or invalid input."""

    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    """Return one conventional boolean setting or its configured default."""

    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class Settings:
    """Gateway configuration, loaded from environment / the gateway `.env` file.

    复制 `.env.example` 为 `.env` 并填入真实值；`.env` 不要提交到 git。
    """

    # --- LLM 分层路由（按 prompt 字符长度选 {url, key, model}）---------------
    # 由 AGENT_BRIDGE_MODELS（JSON map）解析；未配置时为仅含 default 占位层的兜底
    # router（缺 key，真正发请求时由 OpenAI client 报错，与缺 key 行为一致）。
    model_router: ModelRouter = field(
        default_factory=lambda: ModelRouter(default=ModelTier(model="gpt-4o-mini"))
    )

    # --- 数据库（默认 SQLite；PostgreSQL 用 postgresql://...）---------------
    database_url: str = "sqlite:///./data/agent_bridge.sqlite3"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    db_pool_timeout: float = 30.0

    # --- 登录态 cookie ------------------------------------------------------
    # 签名 session cookie 的 HMAC secret；防篡改，不是加密。生产务必替换。
    auth_session_secret: str = "dev-session-secret-change-me"
    # 本地 HTTP 开发为 false；HTTPS 部署应为 true，否则浏览器不发送 Secure cookie。
    auth_cookie_secure: bool = False
    # 登录成功后浏览器最终跳转回的前端地址（简历管理页）。
    auth_frontend_redirect_url: str = "http://127.0.0.1:5173/"
    # 扩展 bearer token 有效期（秒），默认 30 天。
    extension_token_ttl_seconds: int = 30 * 24 * 3600
    # /tasks 是否强制登录：托管 true（须 token/cookie）；自部署 false（匿名直连，token 可选）。
    require_auth: bool = False
    # 单用户 /tasks 限流:窗口内最大次数,0=不限流(自部署默认);窗口秒数默认 1 天。
    task_rate_limit_max: int = 0
    task_rate_limit_window_seconds: int = 86400
    # 不兼容扩展收到 426 后跳转的官方更新地址。
    extension_update_url: str = DEFAULT_EXTENSION_UPDATE_URL

    # --- Casdoor OAuth ------------------------------------------------------
    casdoor_endpoint: str = ""
    casdoor_client_id: str = ""
    casdoor_client_secret: str = ""
    # 必须和 Casdoor 应用 Redirect URLs 完全一致，授权和换 token 两步都用它。
    casdoor_redirect_uri: str = ""
    casdoor_http_timeout: float = 15.0

    # --- 对象存储（简历文件）------------------------------------------------
    # fake（本地联调，不真正存储）/ oss。
    storage_provider: str = "fake"
    # 资源读取基础 URL，与 object_key 拼成最终访问地址（OSS bucket 域名或 CDN）。
    asset_base_url: str = ""
    # 服务端下载文件做解析时的 HTTP 超时，秒。
    asset_http_timeout: float = 30.0
    # 简历文件大小上限（字节）；超过则拒绝。
    resume_max_bytes: int = 10 * 1024 * 1024
    # 阿里云 OSS 配置。
    oss_region: str = "cn-hangzhou"
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        """Load Gateway settings from process environment and the local `.env`."""

        # override=False: 真实环境变量优先于 .env 文件中的值。
        load_dotenv(override=False)
        kwargs: dict = {}
        # AGENT_BRIDGE_MODELS 配了就解析（非法配置会抛 ValueError，立刻暴露）；
        # 没配就用 dataclass 默认的占位兜底 router，保证导入/测试不依赖该变量。
        models_raw = os.getenv("AGENT_BRIDGE_MODELS")
        if models_raw and models_raw.strip():
            kwargs["model_router"] = ModelRouter.from_json(models_raw)
        return cls(
            **kwargs,
            database_url=_get_env_str("DATABASE_URL", cls.database_url),
            db_pool_min_size=_get_env_int("DB_POOL_MIN_SIZE", cls.db_pool_min_size),
            db_pool_max_size=_get_env_int("DB_POOL_MAX_SIZE", cls.db_pool_max_size),
            db_pool_timeout=_get_env_float("DB_POOL_TIMEOUT", cls.db_pool_timeout),
            auth_session_secret=_get_env_str("AUTH_SESSION_SECRET", cls.auth_session_secret),
            auth_cookie_secure=_get_env_bool("AUTH_COOKIE_SECURE", cls.auth_cookie_secure),
            auth_frontend_redirect_url=_get_env_str(
                "AUTH_FRONTEND_REDIRECT_URL", cls.auth_frontend_redirect_url
            ),
            extension_token_ttl_seconds=_get_env_int(
                "EXTENSION_TOKEN_TTL_SECONDS", cls.extension_token_ttl_seconds
            ),
            require_auth=_get_env_bool("REQUIRE_AUTH", cls.require_auth),
            task_rate_limit_max=_get_env_int("TASK_RATE_LIMIT_MAX", cls.task_rate_limit_max),
            task_rate_limit_window_seconds=_get_env_int(
                "TASK_RATE_LIMIT_WINDOW_SECONDS", cls.task_rate_limit_window_seconds
            ),
            extension_update_url=_get_env_str(
                "EXTENSION_UPDATE_URL", cls.extension_update_url
            ),
            casdoor_endpoint=_get_env_str("CASDOOR_ENDPOINT", cls.casdoor_endpoint),
            casdoor_client_id=_get_env_str("CASDOOR_CLIENT_ID", cls.casdoor_client_id),
            casdoor_client_secret=_get_env_str("CASDOOR_CLIENT_SECRET", cls.casdoor_client_secret),
            casdoor_redirect_uri=_get_env_str("CASDOOR_REDIRECT_URI", cls.casdoor_redirect_uri),
            casdoor_http_timeout=_get_env_float("CASDOOR_HTTP_TIMEOUT", cls.casdoor_http_timeout),
            storage_provider=_get_env_str("STORAGE_PROVIDER", cls.storage_provider).lower(),
            asset_base_url=_get_env_str("ASSET_BASE_URL", cls.asset_base_url).rstrip("/"),
            asset_http_timeout=_get_env_float("ASSET_HTTP_TIMEOUT", cls.asset_http_timeout),
            resume_max_bytes=_get_env_int("RESUME_MAX_BYTES", cls.resume_max_bytes),
            oss_region=_get_env_str("OSS_REGION", cls.oss_region),
            oss_bucket=_get_env_str("OSS_BUCKET", cls.oss_bucket),
            oss_access_key_id=_get_env_str("OSS_ACCESS_KEY_ID", cls.oss_access_key_id),
            oss_access_key_secret=_get_env_str("OSS_ACCESS_KEY_SECRET", cls.oss_access_key_secret),
        )


settings = Settings.from_env()
