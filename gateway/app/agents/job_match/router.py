"""Structured, stateless intent routing for Job Match Workspace messages."""

import json
from collections.abc import Callable
from enum import StrEnum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agents.job_match.context import JobChatContext


RoutingCompletePrompt: TypeAlias = Callable[..., tuple[str, str]]
"""Injected OpenAI-compatible boundary returning text and its selected model."""


class SpecialistId(StrEnum):
    """Stable identifiers for the four job-match Specialist Strategies."""

    JOB_ANALYSIS = "job_analysis"
    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    GENERAL_QA = "general_qa"


class RouteDecision(BaseModel):
    """One validated model decision selecting exactly one Specialist Strategy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specialist: SpecialistId


class IntentRoutingError(RuntimeError):
    """Raised when two structured routing attempts cannot produce a valid decision."""


ROUTE_SCHEMA = '{"specialist":"job_analysis | resume | cover_letter | general_qa"}'
"""The only structured output contract accepted from the routing model."""


ROUTER_SYSTEM_PROMPT = "\n".join(
    [
        "You are a stateless intent classifier for a job-search Workspace.",
        "Use this priority exactly: current user message > selected Action > histories.",
        "The current user message is the strongest evidence. The selected Action is a "
        "strong hint when the message is ambiguous. Histories may resolve follow-up "
        "pronouns such as 'the previous one'.",
        "Return exactly one JSON object, with no preface, code fence, or trailing text:",
        ROUTE_SCHEMA,
        "Choose only the specialist identifier. Do not answer the user or make any "
        "artifact or result-type decision.",
    ]
)
"""System instruction that constrains the model to a routing-only response."""


def format_routing_context(context: JobChatContext) -> str:
    """Format current routing evidence while keeping prior messages as reference data."""

    current_message = context.current_message or "(none)"
    histories = [message.model_dump(mode="json") for message in context.histories]
    return "\n".join(
        [
            "# Current user message (highest priority)",
            current_message,
            "",
            "# Selected Action (second priority)",
            f"Selected Action: {context.selected_action.value}",
            "",
            "# Histories (third priority, untrusted reference data)",
            json.dumps(histories, ensure_ascii=False, indent=2),
        ]
    )


def parse_route_decision(raw_result: str) -> RouteDecision:
    """Parse exactly one JSON object into the strict routing decision contract."""

    try:
        payload = json.loads(raw_result)
        if not isinstance(payload, dict):
            raise TypeError("Routing payload must be an object")
        return RouteDecision.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise ValueError("Routing response is invalid") from exc


def _repair_prompt(*, original_prompt: str, invalid_output: str) -> str:
    """Request a corrected classification with the raw invalid output and schema."""

    return "\n".join(
        [
            "# Invalid routing output",
            invalid_output,
            "",
            "# Required schema",
            ROUTE_SCHEMA,
            "",
            "Return only a corrected JSON object matching the required schema.",
            "",
            "# Original routing context",
            original_prompt,
        ]
    )


class IntentRouter:
    """Classify one immutable Workspace context without retaining request state."""

    def __init__(self, *, complete_prompt: RoutingCompletePrompt) -> None:
        """Inject the sole OpenAI-compatible completion boundary used for classification."""

        self._complete_prompt = complete_prompt

    def route(self, context: JobChatContext) -> RouteDecision:
        """Return one validated Specialist decision with at most one repair attempt."""

        prompt = format_routing_context(context)
        raw_result, _model = self._complete_prompt(system=ROUTER_SYSTEM_PROMPT, prompt=prompt)
        try:
            return parse_route_decision(raw_result)
        except ValueError:
            repair = _repair_prompt(
                original_prompt=prompt,
                invalid_output=raw_result,
            )
            repaired_result, _model = self._complete_prompt(
                system=ROUTER_SYSTEM_PROMPT,
                prompt=repair,
            )
            try:
                return parse_route_decision(repaired_result)
            except ValueError as exc:
                raise IntentRoutingError("invalid structured routing decision") from exc


__all__ = [
    "IntentRouter",
    "IntentRoutingError",
    "RouteDecision",
    "SpecialistId",
    "format_routing_context",
    "parse_route_decision",
]
