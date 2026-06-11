import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _get_env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


def _get_env_int(name: str, default: int) -> int:
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


@dataclass(frozen=True)
class Settings:
    """Gateway configuration, loaded from environment / the gateway `.env` file.

    复制 `.env.example` 为 `.env` 并填入真实值；`.env` 不要提交到 git。
    """

    # OpenAI 或任意 OpenAI 兼容服务的 API key。
    openai_api_key: str = ""
    # 接口地址；留空用 OpenAI 官方地址。
    openai_base_url: str = ""
    # 模型 id。
    model: str = "gpt-4o-mini"
    # 长输入(prompt 超过 route_threshold_chars 字符)改用的模型 id;
    # 留空则不路由,所有任务统一用 model。
    model_long: str = ""
    # prompt 超过该字符数视为"长输入"。
    route_threshold_chars: int = 8000

    @classmethod
    def from_env(cls) -> "Settings":
        # override=False: 真实环境变量优先于 .env 文件中的值。
        load_dotenv(override=False)
        return cls(
            openai_api_key=_get_env_str("OPENAI_API_KEY", cls.openai_api_key),
            openai_base_url=_get_env_str("OPENAI_BASE_URL", cls.openai_base_url),
            model=_get_env_str("AGENT_BRIDGE_MODEL", cls.model),
            model_long=_get_env_str("AGENT_BRIDGE_MODEL_LONG", cls.model_long),
            route_threshold_chars=_get_env_int(
                "AGENT_BRIDGE_ROUTE_THRESHOLD", cls.route_threshold_chars
            ),
        )


settings = Settings.from_env()
