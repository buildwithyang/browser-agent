"""Strict asynchronous intent routing for Job Match Workspace messages."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from app.agents.job_match.context import JobChatContext
from app.modules.task.schema import Artifact

if TYPE_CHECKING:
    from app.agents.job_match.specialists.base import JobMatchSpecialist


AsyncCompletePrompt: TypeAlias = Callable[..., Awaitable[tuple[str, str]]]
"""Asynchronous Chat Completions boundary returning text and selected model."""

ROUTER_HISTORY_MESSAGES = 4
"""Maximum recent text messages supplied to the routing model."""


class SpecialistId(StrEnum):
    """Stable identifiers for the four job-match Specialist Strategies."""

    JOB_ANALYSIS = "job_analysis"
    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    GENERAL_QA = "general_qa"


class OutputMode(StrEnum):
    """Whether one Specialist returns a chat reply or a complete Artifact draft."""

    REPLY = "reply"
    ARTIFACT = "artifact"


class RoutingDecision(BaseModel):
    """Validated Specialist handoff for one Workspace turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specialist: str = Field(min_length=1, max_length=100)
    output_mode: OutputMode
    instruction: str = Field(min_length=1, max_length=2000)

    @field_validator("instruction")
    @classmethod
    def validate_instruction(cls, value: str) -> str:
        """Reject an empty handoff and normalize harmless surrounding whitespace."""

        instruction = value.strip()
        if not instruction:
            raise ValueError("instruction must contain text")
        return instruction


class IntentRoutingError(RuntimeError):
    """Raised when two routing attempts cannot produce a valid decision."""


ROUTING_SCHEMA = (
    '{"specialist":"registered specialist id",'
    '"output_mode":"reply | artifact","instruction":"non-empty execution instruction"}'
)
"""The only structured output contract accepted from the routing model."""


ROUTER_BASE_SYSTEM_PROMPT = "\n".join(
    [
        "You are a stateless intent router for a job-search Workspace.",
        "Use this priority exactly: current message > current artifacts > histories.",
        "The current user message is authoritative. Recent history may only resolve "
        "follow-up references such as 'the previous one'.",
        "Choose reply for advice, explanation, analysis, or questions. Choose artifact "
        "only for an explicit request to generate or rewrite a complete CV or cover letter.",
        "When a relevant Artifact exists, a direct edit or transformation such as "
        "'make it shorter', 'translate it', or '生成的简短一点' must choose artifact.",
        "Write instruction as a concise operational handoff to the selected Specialist. "
        "It must preserve exact user-provided literals and proper names, add no facts or "
        "requirements, and must not answer the user.",
        "Return exactly one JSON object, with no preface, code fence, or trailing text:",
        ROUTING_SCHEMA,
        "Choose only a Specialist and output mode listed in the registered catalogue.",
    ]
)
"""System instruction constraining the model to routing and explicit handoff only."""


def _artifact_metadata(context: JobChatContext) -> dict[str, object | None]:
    """Return routing metadata without exposing current Artifact draft content."""

    def metadata(artifact: Artifact | None) -> dict[str, object] | None:
        """Project one optional Artifact to stable routing fields."""

        if artifact is None:
            return None
        return {
            "type": artifact.type.value,
            "version": artifact.version,
            "title": artifact.title,
        }

    return {
        "cv": metadata(context.artifacts.cv),
        "cover_letter": metadata(context.artifacts.cover_letter),
    }


def format_routing_context(context: JobChatContext) -> str:
    """Format minimal routing evidence without drafts or historical Attachments."""

    histories = [
        {"role": message.role, "content": message.content}
        for message in context.histories[-ROUTER_HISTORY_MESSAGES:]
    ]
    return "\n".join(
        [
            "# Current user message",
            context.current_message,
            "",
            "# Current artifact metadata",
            json.dumps(_artifact_metadata(context), ensure_ascii=False, indent=2),
            "",
            "# Recent conversation text",
            json.dumps(histories, ensure_ascii=False, indent=2),
        ]
    )


def parse_routing_decision(raw_result: str) -> RoutingDecision:
    """Parse exactly one JSON object into the strict routing contract."""

    try:
        payload = json.loads(raw_result)
        if not isinstance(payload, dict):
            raise TypeError("Routing payload must be an object")
        return RoutingDecision.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValidationError):
        raise ValueError("Routing response is invalid") from None


def _repair_prompt(*, original_prompt: str, invalid_output: str) -> str:
    """Request one corrected decision using the invalid output and exact schema."""

    return "\n".join(
        [
            "# Invalid routing output",
            invalid_output,
            "",
            "# Required schema",
            ROUTING_SCHEMA,
            "",
            "Return only a corrected JSON object matching the required schema.",
            "",
            "# Original routing context",
            original_prompt,
        ]
    )


class IntentRouter:
    """Route one immutable Workspace turn without retaining request state."""

    def __init__(
        self,
        *,
        complete_prompt: AsyncCompletePrompt,
        specialists: Mapping[str, JobMatchSpecialist],
    ) -> None:
        """Inject the model boundary and registered Specialist instances."""

        self._complete_prompt = complete_prompt
        self.specialists = dict(specialists)

    def _system_prompt(self) -> str:
        """Build the routing prompt from the currently registered capabilities."""

        catalogue = [
            {
                "id": specialist_id,
                "description": specialist.description,
                "output_modes": sorted(mode.value for mode in specialist.allowed_modes),
            }
            for specialist_id, specialist in self.specialists.items()
        ]
        return "\n\n".join(
            [
                ROUTER_BASE_SYSTEM_PROMPT,
                "# Registered specialists",
                json.dumps(catalogue, ensure_ascii=False, indent=2),
            ]
        )

    def resolve_specialist(self, specialist_id: str) -> JobMatchSpecialist:
        """Resolve one registered Specialist by its stable routing ID."""

        try:
            return self.specialists[specialist_id]
        except KeyError:
            raise IntentRoutingError(
                f"Specialist is not registered: {specialist_id}"
            ) from None

    def _parse_and_validate(self, raw_result: str) -> RoutingDecision:
        """Validate structured output against the current Specialist Map."""

        decision = parse_routing_decision(raw_result)
        specialist = self.specialists.get(decision.specialist)
        if specialist is None or decision.output_mode not in specialist.allowed_modes:
            raise ValueError("Routing response selects an unavailable capability")
        return decision

    async def route(self, context: JobChatContext) -> RoutingDecision:
        """Return one strict routing decision with at most one repair attempt."""

        prompt = format_routing_context(context)
        system = self._system_prompt()
        raw_result, _model = await self._complete_prompt(
            system=system,
            prompt=prompt,
        )
        try:
            return self._parse_and_validate(raw_result)
        except ValueError:
            repair = _repair_prompt(original_prompt=prompt, invalid_output=raw_result)
            repaired_result, _model = await self._complete_prompt(
                system=system,
                prompt=repair,
            )
            try:
                return self._parse_and_validate(repaired_result)
            except ValueError:
                raise IntentRoutingError("invalid structured intent route") from None


__all__ = [
    "AsyncCompletePrompt",
    "IntentRouter",
    "IntentRoutingError",
    "OutputMode",
    "RoutingDecision",
    "SpecialistId",
    "format_routing_context",
    "parse_routing_decision",
]
