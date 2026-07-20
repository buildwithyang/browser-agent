import asyncio
from types import SimpleNamespace
from typing import AsyncIterator

from pytest import MonkeyPatch

from app.agents.base import (
    AgentExecution,
    OpenAIChatAgent,
    StreamingWorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.model_router import ModelRouter, ModelTier
from app.agents.stream import (
    AgentCompleted,
    AgentDelta,
    AgentStatus,
    AgentStreamEvent,
)
from app.modules.task.schema import AgentName, ReplyResult


class FakeAsyncChatCompletionStream:
    """Yield OpenAI-compatible Chat Completion chunks for boundary tests."""

    def __init__(self, texts: list[str | None]) -> None:
        """Store the ordered text deltas returned by the fake provider."""

        self._texts = texts
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        """Yield complete chunk shapes consumed by the production adapter."""

        for text in self._texts:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
            )

    async def aclose(self) -> None:
        """Record deterministic provider-stream cleanup."""

        self.closed = True


class FakeAsyncClient:
    """Expose the AsyncOpenAI Chat Completions surface used by the Agent."""

    def __init__(self, texts: list[str | None]) -> None:
        """Configure fake output and capture provider requests."""

        self._texts = texts
        self.calls: list[dict[str, object]] = []
        self.streams: list[FakeAsyncChatCompletionStream] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    async def _create(self, **kwargs: object) -> object:
        """Return either a complete response or an asynchronous chunk stream."""

        self.calls.append(kwargs)
        if kwargs.get("stream") is True:
            stream = FakeAsyncChatCompletionStream(self._texts)
            self.streams.append(stream)
            return stream
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._texts[0])
                )
            ]
        )


def test_open_prompt_stream_yields_non_empty_text_in_order() -> None:
    """Adapt provider chunks into one ordered provider-independent text stream."""

    async def collect() -> tuple[str, list[str], list[dict[str, object]]]:
        """Open and fully consume one fake model stream."""

        client = FakeAsyncClient([None, "这个岗", "", "位"])
        agent = OpenAIChatAgent(
            router=ModelRouter(default=ModelTier(model="fake-model")),
            async_client=client,
        )
        opened = await agent.open_prompt_stream(system="system", prompt="prompt")
        return opened.model, [chunk async for chunk in opened.chunks], client.calls

    model, chunks, calls = asyncio.run(collect())

    assert (model, chunks) == ("fake-model", ["这个岗", "位"])
    assert calls == [
        {
            "model": "fake-model",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "prompt"},
            ],
            "stream": True,
        }
    ]


def test_async_completion_uses_non_streaming_chat_completions() -> None:
    """Keep planner-style async completion on Chat Completions without streaming."""

    async def execute() -> tuple[str, str, list[dict[str, object]]]:
        """Run one complete fake provider request."""

        client = FakeAsyncClient(["planner result"])
        agent = OpenAIChatAgent(
            router=ModelRouter(default=ModelTier(model="router-model")),
            async_client=client,
        )
        text, model = await agent.acomplete_prompt(system="system", prompt="prompt")
        return text, model, client.calls

    text, model, calls = asyncio.run(execute())

    assert (text, model) == ("planner result", "router-model")
    assert calls[0]["stream"] is False


def test_closing_text_chunks_closes_the_provider_stream() -> None:
    """Forward consumer cancellation to the underlying provider iterator."""

    async def execute() -> bool:
        """Consume one text chunk, close the adapter, and return provider state."""

        client = FakeAsyncClient(["first", "second"])
        agent = OpenAIChatAgent(async_client=client, model="stream-model")
        opened = await agent.open_prompt_stream(system="system", prompt="prompt")
        assert await anext(opened.chunks) == "first"
        await opened.chunks.aclose()
        return client.streams[0].closed

    assert asyncio.run(execute()) is True


def test_async_clients_are_cached_by_provider_identity(monkeypatch: MonkeyPatch) -> None:
    """Reuse one production async client for repeated calls to the same tier."""

    constructed: list[dict[str, object]] = []

    def build_client(**kwargs: object) -> FakeAsyncClient:
        """Capture construction and return a complete Chat Completions fake."""

        constructed.append(kwargs)
        return FakeAsyncClient(["result"])

    monkeypatch.setattr("app.agents.base.AsyncOpenAI", build_client)
    agent = OpenAIChatAgent(
        router=ModelRouter(
            default=ModelTier(
                model="model",
                url="https://provider.example/v1",
                key="provider-key",
            )
        )
    )

    async def execute_twice() -> None:
        """Run two requests through one provider identity."""

        await agent.acomplete_prompt(system="system", prompt="first")
        await agent.acomplete_prompt(system="system", prompt="second")

    asyncio.run(execute_twice())

    assert constructed == [
        {"api_key": "provider-key", "base_url": "https://provider.example/v1"}
    ]


def test_agent_stream_types_keep_provider_details_out_of_business_events() -> None:
    """Represent progress, Markdown, and completion with small immutable values."""

    execution = AgentExecution(
        content=ReplyResult(type="reply", markdown="Done"),
        raw_result="Done",
        prompt="prompt",
        model="model",
    )
    events: list[AgentStreamEvent] = [
        AgentStatus(stage="routing"),
        AgentDelta(text="Done"),
        AgentCompleted(execution=execution),
    ]

    assert events[0].stage == "routing"
    assert events[1].text == "Done"
    assert events[2].execution is execution


def test_streaming_workspace_agent_is_an_explicit_runtime_contract() -> None:
    """Recognize stateless Workspace Agents that expose an async event stream."""

    class FakeStreamingWorkspaceAgent:
        """Implement the minimal streaming Workspace Agent contract."""

        name = AgentName.SUMMARY_PAGE
        requires_resume = False

        async def stream_chat(
            self, context: WorkspaceAgentContext
        ) -> AsyncIterator[AgentStreamEvent]:
            """Yield no events for this structural contract test."""

            if False:
                yield AgentStatus(stage="routing")

    assert isinstance(FakeStreamingWorkspaceAgent(), StreamingWorkspaceAgent)
