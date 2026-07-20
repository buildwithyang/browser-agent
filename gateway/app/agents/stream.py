"""Provider-independent values for asynchronous Agent text streams."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator, Literal, TypeVar

from openai.types.chat import ChatCompletionChunk

from app.modules.task.schema import ArtifactType, ChatResult

if TYPE_CHECKING:
    from app.agents.base import AgentExecution

ChunkT = TypeVar("ChunkT")


@dataclass(frozen=True)
class ModelTextStream:
    """Selected model and one provider-independent asynchronous text stream."""

    model: str
    chunks: AsyncIterator[str]


@dataclass(frozen=True)
class AgentStatus:
    """One business progress update from a streaming Workspace Agent."""

    stage: Literal[
        "routing",
        "generating_reply",
        "generating_artifact",
        "finalizing",
    ]
    artifact_type: ArtifactType | None = None


@dataclass(frozen=True)
class AgentDelta:
    """One non-empty Markdown text fragment from a Workspace Agent."""

    text: str


@dataclass(frozen=True)
class AgentCompleted:
    """One validated terminal execution from a streaming Workspace Agent."""

    execution: AgentExecution[ChatResult]


AgentStreamEvent = AgentStatus | AgentDelta | AgentCompleted


@asynccontextmanager
async def closing_if_supported(
    iterator: AsyncIterator[ChunkT],
) -> AsyncIterator[AsyncIterator[ChunkT]]:
    """Close an async iterator on exit only when it exposes ``aclose``."""

    try:
        yield iterator
    finally:
        close = getattr(iterator, "aclose", None)
        if callable(close):
            await close()


async def _text_chunks(
    stream: AsyncIterator[ChatCompletionChunk],
) -> AsyncIterator[str]:
    """Yield only non-empty text deltas from Chat Completions chunks."""

    try:
        async for chunk in stream:
            text = chunk.choices[0].delta.content if chunk.choices else None
            if text:
                yield text
    finally:
        close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
        if close is not None:
            await close()
