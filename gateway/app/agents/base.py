import os
from abc import ABC, abstractmethod

from openai import OpenAI

from app.models import TaskCreate

DEFAULT_MODEL = os.environ.get("AGENT_BRIDGE_MODEL", "gpt-4o-mini")

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
        client: OpenAI | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model_long: str | None = None,
        route_threshold_chars: int = 8000,
    ) -> None:
        self._client = client
        self.model = model or DEFAULT_MODEL
        self.model_long = model_long or ""
        self.route_threshold_chars = route_threshold_chars
        self._api_key = api_key
        self._base_url = base_url

    @property
    def client(self) -> OpenAI:
        # Lazily construct so importing never requires an API key. Explicit
        # api_key / base_url win; None falls back to the OPENAI_* env vars.
        if self._client is None:
            kwargs = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def pick_model(self, prompt: str) -> str:
        """按输入长度路由:长输入用 model_long(若配置),保证大页面也能快速返回。"""
        if self.model_long and len(prompt) > self.route_threshold_chars:
            return self.model_long
        return self.model

    def complete(self, system: str, user: str, model: str | None = None) -> str:
        response = self.client.chat.completions.create(
            model=model or self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def run(self, task: TaskCreate) -> str:
        system = self.system_prompt + "\n\n" + language_directive(task.lang)
        prompt = self.build_prompt(task)
        return self.complete(system, prompt, model=self.pick_model(prompt))
