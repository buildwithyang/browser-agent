"""Quick Insight and streaming Workspace tests for the generic page Agent."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast

import pytest

from app.agents.base import (
    AgentContext,
    QuickInsightAgent,
    StreamingWorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.stream import AgentCompleted, AgentDelta, AgentStatus, AgentStreamEvent
from app.modules.task.schema import (
    ActionId,
    DOCUMENT_TEXT_MAX_CHARS,
    QuickInsightRequest,
    ReplyResult,
    UserMessageWorkspaceRequest,
)
from app.agents.summary_page import SummaryPageAgent


class FakeAsyncStream:
    """Yield configured OpenAI-compatible Chat Completion chunks."""

    def __init__(self, chunks: list[str]) -> None:
        """Store the raw text chunks emitted by the fake provider."""

        self.chunks = chunks

    async def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        """Yield provider chunk shapes consumed by the shared adapter."""

        for text in self.chunks:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
            )


class FakeAsyncClient:
    """Expose one observable AsyncOpenAI-compatible client."""

    def __init__(self, chunks: list[str]) -> None:
        """Configure streaming output and initialize the call log."""

        self.chunks = chunks
        self.calls: list[dict[str, object]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: object) -> object:
        """Record the request and return the configured stream."""

        self.calls.append(kwargs)
        return FakeAsyncStream(self.chunks)


def full_page_task() -> QuickInsightRequest:
    """Build a generic Quick Insight request without selected text."""

    return QuickInsightRequest(
        intent="Analyze this job for resume fit.",
        url="https://example.com/jobs/123",
        title="Senior Golang Engineer",
        selected_text="",
        page_text="We need Go, Kubernetes, and backend experience.",
        image_text="Org chart diagram · Office photo",
    )


def selection_task() -> QuickInsightRequest:
    """Build a generic Quick Insight request focused on selected text."""

    return QuickInsightRequest(
        url="https://example.com/jobs/123",
        title="Senior Golang Engineer",
        selected_text="Dubai remote role, visa sponsored",
        page_text="We need Go, Kubernetes, and backend experience.",
        image_text="Org chart diagram",
    )


def workspace_request(
    *,
    action_id: ActionId = ActionId.ASK_MORE,
    message: str = "When does it ship?",
    lang: str = "en",
) -> UserMessageWorkspaceRequest:
    """Build a v2 Workspace chat request for the streaming Agent contract."""

    return UserMessageWorkspaceRequest(
        trigger="user_message",
        url="https://example.com/article",
        resourceUrl="https://example.com/article",
        operationId="00000000-0000-0000-0000-000000000001",
        title="Release Notes",
        pageText="Version 2.0 ships Friday.",
        actionId=action_id,
        histories=[{"role": "assistant", "content": "The release is ready."}],
        artifacts={"cv": None, "cover_letter": None},
        message=message,
        lang=lang,
    )


async def _collect_events(stream: AsyncIterator[AgentStreamEvent]) -> list[AgentStreamEvent]:
    """Collect one Agent event stream for synchronous tests."""

    return [event async for event in stream]


def test_full_page_prompt_contains_page_and_image_clues() -> None:
    """Include all generic page evidence when no selection exists."""

    prompt = SummaryPageAgent().build_prompt(full_page_task())

    assert "Analyze this job for resume fit." in prompt
    assert "Senior Golang Engineer" in prompt
    assert "We need Go, Kubernetes" in prompt
    assert "Org chart diagram" in prompt


def test_selection_prompt_focuses_on_selection() -> None:
    """Exclude unrelated page evidence when selected text is present."""

    prompt = SummaryPageAgent().build_prompt(selection_task())

    assert "Dubai remote role, visa sponsored" in prompt
    assert "selected" in prompt.lower()
    assert "We need Go, Kubernetes" not in prompt
    assert "Org chart diagram" not in prompt


def test_summary_builds_generic_quick_insight() -> None:
    """Render synchronous Quick Insight Markdown into the generic card."""

    agent = SummaryPageAgent()
    insight = agent.build_insight("**Release:** Version 2.0 ships Friday.", "en")

    assert insight.title == "Page Summary"
    assert "<strong>Release:</strong>" in insight.cards[0].body_html


def test_summary_declares_only_ask_more() -> None:
    """Expose only the stable Ask More action for a generic page."""

    agent = SummaryPageAgent()
    request = full_page_task().model_copy(update={"lang": "en"})

    actions = agent.available_actions(AgentContext(request=request))

    assert isinstance(agent, QuickInsightAgent)
    assert [action.id for action in actions] == [ActionId.ASK_MORE]
    assert [action.title for action in actions] == ["Ask More"]


def test_summary_workspace_streams_reply_only_markdown() -> None:
    """Expose reply deltas and one terminal ReplyResult without a planner."""

    client = FakeAsyncClient(["It ships", " Friday."])
    agent = SummaryPageAgent(async_client=client, model="summary-model")

    events = asyncio.run(
        _collect_events(
            agent.stream_chat(WorkspaceAgentContext(request=workspace_request()))
        )
    )

    assert isinstance(agent, StreamingWorkspaceAgent)
    assert [event.text for event in events if isinstance(event, AgentDelta)] == [
        "It ships",
        " Friday.",
    ]
    assert [event.stage for event in events if isinstance(event, AgentStatus)] == [
        "generating_reply",
        "finalizing",
    ]
    completed = cast(AgentCompleted, events[-1])
    assert completed.execution.content == ReplyResult(
        type="reply",
        markdown="It ships Friday.",
    )
    assert completed.execution.raw_result == "It ships Friday."
    assert completed.execution.model == "summary-model"
    assert "When does it ship?" in completed.execution.prompt
    assert "ask_more" in completed.execution.prompt
    assert "Version 2.0 ships Friday." in completed.execution.prompt
    assert "Respond entirely in English" in cast(
        list[dict[str, str]], client.calls[0]["messages"]
    )[0]["content"]


def test_summary_workspace_rejects_non_ask_more_before_model_call() -> None:
    """Reject non-generic v2 Actions without opening a model stream."""

    client = FakeAsyncClient(["unexpected"])
    agent = SummaryPageAgent(async_client=client, model="m")

    with pytest.raises(ValueError, match="Unsupported workspace action"):
        asyncio.run(
            _collect_events(
                agent.stream_chat(
                    WorkspaceAgentContext(
                        request=workspace_request(action_id=ActionId.ANALYZE)
                    )
                )
            )
        )

    assert client.calls == []


@pytest.mark.parametrize(
    ("chunks", "message"),
    [([], "must contain Markdown"), ([" \n"], "must contain Markdown")],
)
def test_summary_workspace_rejects_empty_stream(
    chunks: list[str],
    message: str,
) -> None:
    """Reject empty Markdown before emitting a terminal result."""

    agent = SummaryPageAgent(async_client=FakeAsyncClient(chunks), model="m")

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            _collect_events(
                agent.stream_chat(WorkspaceAgentContext(request=workspace_request()))
            )
        )


def test_summary_workspace_rejects_stream_over_document_limit() -> None:
    """Stop generic reply accumulation after the shared 100k limit."""

    client = FakeAsyncClient(["x" * DOCUMENT_TEXT_MAX_CHARS, "y"])
    agent = SummaryPageAgent(async_client=client, model="m")

    with pytest.raises(ValueError, match="100000"):
        asyncio.run(
            _collect_events(
                agent.stream_chat(WorkspaceAgentContext(request=workspace_request()))
            )
        )
