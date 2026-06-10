import os
from abc import ABC, abstractmethod

from openai import OpenAI

from app.models import TaskCreate

DEFAULT_MODEL = os.environ.get("AGENT_BRIDGE_MODEL", "gpt-4o-mini")


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
    ) -> None:
        self._client = client
        self.model = model or DEFAULT_MODEL
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

    def complete(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def run(self, task: TaskCreate) -> str:
        return self.complete(self.system_prompt, self.build_prompt(task))
