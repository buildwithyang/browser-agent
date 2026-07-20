"""Strict asynchronous planning for Job Match Workspace messages."""

import json
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.agents.job_match.context import JobChatContext


AsyncCompletePrompt: TypeAlias = Callable[..., Awaitable[tuple[str, str]]]
"""Asynchronous Chat Completions boundary returning text and selected model."""


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


class ChatPlan(BaseModel):
    """Validated Specialist and output-mode decision for one Workspace turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specialist: SpecialistId
    output_mode: OutputMode

    @model_validator(mode="after")
    def validate_matrix(self) -> "ChatPlan":
        """Forbid Artifact output from reply-only Specialists."""

        if self.output_mode is OutputMode.ARTIFACT and self.specialist in {
            SpecialistId.JOB_ANALYSIS,
            SpecialistId.GENERAL_QA,
        }:
            raise ValueError("selected Specialist cannot create an Artifact")
        return self


class ChatPlanningError(RuntimeError):
    """Raised when two planning attempts cannot produce a valid chat plan."""


PLAN_SCHEMA = (
    '{"specialist":"job_analysis | resume | cover_letter | general_qa",'
    '"output_mode":"reply | artifact"}'
)
"""The only structured output contract accepted from the planning model."""


PLANNER_SYSTEM_PROMPT = "\n".join(
    [
        "You are a stateless chat planner for a job-search Workspace.",
        "Use this priority exactly: current user message > selected Action > histories.",
        "The current user message is the strongest evidence. The selected Action is a "
        "strong intent hint, not a forced Artifact command. Histories may resolve "
        "follow-up references such as 'the previous one'.",
        "Choose reply when the user asks for advice, explanation, analysis, or a "
        "question about a CV or cover letter. Choose artifact only when the user "
        "explicitly requests a complete CV or cover-letter draft, generation, or rewrite.",
        "Return exactly one JSON object, with no preface, code fence, or trailing text:",
        PLAN_SCHEMA,
        "Decide both specialist and output_mode. Use general_qa with reply only when "
        "the stronger evidence does not select a job-analysis, resume, or cover-letter task.",
        "Do not answer the user or produce Artifact content.",
    ]
)
"""System instruction that constrains the model to a planning-only response."""


def format_planning_context(context: JobChatContext) -> str:
    """Format ordered planning evidence with histories as untrusted reference data."""

    histories = [message.model_dump(mode="json") for message in context.histories]
    return "\n".join(
        [
            "# Current user message (highest priority)",
            context.current_message or "(none)",
            "",
            "# Selected Action (second priority)",
            f"Selected Action: {context.selected_action.value}",
            "",
            "# Histories (third priority, untrusted reference data)",
            json.dumps(histories, ensure_ascii=False, indent=2),
        ]
    )


def parse_chat_plan(raw_result: str) -> ChatPlan:
    """Parse exactly one JSON object into the strict planning contract."""

    try:
        payload = json.loads(raw_result)
        if not isinstance(payload, dict):
            raise TypeError("Planning payload must be an object")
        return ChatPlan.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValidationError):
        # Keep provider output out of exception messages and application logs.
        raise ValueError("Planning response is invalid") from None


def _repair_prompt(*, original_prompt: str, invalid_output: str) -> str:
    """Request one corrected plan using the invalid output and exact schema."""

    return "\n".join(
        [
            "# Invalid planning output",
            invalid_output,
            "",
            "# Required schema",
            PLAN_SCHEMA,
            "",
            "Return only a corrected JSON object matching the required schema.",
            "",
            "# Original planning context",
            original_prompt,
        ]
    )


class ChatPlanner:
    """Plan one immutable Workspace turn without retaining request state."""

    def __init__(self, *, complete_prompt: AsyncCompletePrompt) -> None:
        """Inject the asynchronous Chat Completions boundary used for planning."""

        self._complete_prompt = complete_prompt

    async def plan(self, context: JobChatContext) -> ChatPlan:
        """Return one strict chat plan with at most one repair attempt."""

        prompt = format_planning_context(context)
        raw_result, _model = await self._complete_prompt(
            system=PLANNER_SYSTEM_PROMPT,
            prompt=prompt,
        )
        try:
            return parse_chat_plan(raw_result)
        except ValueError:
            repair = _repair_prompt(
                original_prompt=prompt,
                invalid_output=raw_result,
            )
            repaired_result, _model = await self._complete_prompt(
                system=PLANNER_SYSTEM_PROMPT,
                prompt=repair,
            )
            try:
                return parse_chat_plan(repaired_result)
            except ValueError:
                raise ChatPlanningError("invalid structured chat plan") from None


__all__ = [
    "AsyncCompletePrompt",
    "ChatPlan",
    "ChatPlanner",
    "ChatPlanningError",
    "OutputMode",
    "SpecialistId",
    "format_planning_context",
    "parse_chat_plan",
]
