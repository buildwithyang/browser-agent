from abc import ABC, abstractmethod

from openai import OpenAI

from app.agents.model_router import ModelRouter, ModelTier
from app.modules.task.schema import TaskCreate

DEFAULT_MODEL = "gpt-4o-mini"

# Output-language directives, appended last to the system prompt so they win
# regardless of the language the prompt body is written in.
LANGUAGE_DIRECTIVES = {
    "zh": "无论页面或材料是什么语言,都请用简体中文回复(包括所有小标题)。",
    "en": "Respond entirely in English (including all section headings), "
    "regardless of the language of the page or materials.",
    "auto": "Respond in the same language as the page content.",
}


def language_directive(lang: str) -> str:
    return LANGUAGE_DIRECTIVES.get(lang, LANGUAGE_DIRECTIVES["auto"])


class AgentAdapter(ABC):
    name: str

    @abstractmethod
    def build_prompt(self, task: TaskCreate) -> str:
        """Render the task into a single user-message prompt."""
        raise NotImplementedError

    @abstractmethod
    def run(self, task: TaskCreate) -> str:
        """Execute the task and return the agent's result text."""
        raise NotImplementedError


class OpenAIChatAgent(AgentAdapter):
    """Base for agents that call an OpenAI-compatible chat model.

    Subclasses set `system_prompt` and implement `build_prompt`.
    """

    system_prompt: str = ""

    def __init__(
        self,
        router: ModelRouter | None = None,
        *,
        client: OpenAI | None = None,
        model: str | None = None,
    ) -> None:
        # 无 router(测试/简单场景):用固定 model 合成一个单层 default router。
        if router is None:
            router = ModelRouter(default=ModelTier(model=model or DEFAULT_MODEL))
        self._router = router
        # 注入的 client 用于所有层(测试);否则按 (url,key) 懒构建并缓存,同厂多层共用。
        self._injected_client = client
        self._clients: dict[tuple[str, str], OpenAI] = {}

    def _client_for(self, tier: ModelTier) -> OpenAI:
        if self._injected_client is not None:
            return self._injected_client
        cache_key = (tier.url, tier.key)
        client = self._clients.get(cache_key)
        if client is None:
            # Explicit url / key win; empty falls back to the OpenAI SDK defaults.
            kwargs = {}
            if tier.key:
                kwargs["api_key"] = tier.key
            if tier.url:
                kwargs["base_url"] = tier.url
            client = OpenAI(**kwargs)
            self._clients[cache_key] = client
        return client

    def pick_model(self, prompt: str) -> str:
        """按输入长度路由到某一层,返回其 model id(供指标/日志使用)。"""
        return self._router.pick(len(prompt)).model

    def complete(self, system: str, user: str, tier: ModelTier) -> str:
        response = self._client_for(tier).chat.completions.create(
            model=tier.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def run(self, task: TaskCreate) -> str:
        system = self.system_prompt + "\n\n" + language_directive(task.lang)
        prompt = self.build_prompt(task)
        return self.complete(system, prompt, tier=self._router.pick(len(prompt)))
