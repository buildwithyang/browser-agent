import os

from openai import OpenAI

from app.agents.base import AgentAdapter
from app.models import TaskCreate

SYSTEM_PROMPT = (
    "You are Agent Bridge, a helpful assistant that receives the content a user "
    "is currently viewing in their browser. Analyze the provided page context "
    "against the user's intent and respond with concrete, actionable next steps. "
    "Be concise and structured."
)

DEFAULT_MODEL = os.environ.get("AGENT_BRIDGE_MODEL", "gpt-4o-mini")


class SimpleAgent(AgentAdapter):
    name = "simple"

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
        # Lazily construct so importing this module never requires an API key.
        # Explicit api_key / base_url win; anything left as None falls back to the
        # OPENAI_API_KEY / OPENAI_BASE_URL environment variables.
        if self._client is None:
            kwargs = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def build_prompt(self, task: TaskCreate) -> str:
        return "\n".join(
            [
                "User intent:",
                task.intent.strip(),
                "",
                "Page URL:",
                task.url,
                "",
                "Page title:",
                task.title,
                "",
                "Selected text:",
                task.selected_text.strip() or "(none)",
                "",
                "Page text:",
                task.page_text.strip() or "(none)",
            ]
        )

    def run(self, task: TaskCreate) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self.build_prompt(task)},
            ],
        )
        return response.choices[0].message.content or ""
