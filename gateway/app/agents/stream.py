"""Provider-independent values for asynchronous Agent text streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator, Literal

from openai.types.chat import ChatCompletionChunk

from app.modules.task.schema import ArtifactType, ChatResult

if TYPE_CHECKING:
    from app.agents.base import AgentExecution


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


async def _text_chunks(
    stream: AsyncIterator[ChatCompletionChunk],
) -> AsyncIterator[str]:
    """Yield only non-empty text deltas from Chat Completions chunks."""

    async for chunk in stream:
        text = chunk.choices[0].delta.content if chunk.choices else None
        if text:
            yield text
