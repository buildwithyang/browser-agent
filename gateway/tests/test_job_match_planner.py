"""Contract tests for asynchronous job-match chat planning."""

import asyncio
import json
from collections.abc import Awaitable, Callable

import pytest

from app.agents.job_match.context import JobChatContext
from app.agents.job_match.planner import (
    ChatPlan,
    ChatPlanner,
    ChatPlanningError,
    OutputMode,
    SpecialistId,
)
from app.modules.task.schema import (
    ActionId,
    Artifacts,
    HistoryMessage,
    UserMessageWorkspaceRequest,
    WorkspaceTrigger,
)


LONG_JD = (
    "Senior Backend Engineer responsible for distributed Go services, APIs, "
    "Kubernetes, observability, reliability, and cross-team architecture. "
) * 12


def context(
    *,
    action: ActionId = ActionId.ASK_MORE,
    message: str = "What should I emphasize?",
    histories: list[HistoryMessage] | None = None,
) -> JobChatContext:
    """Build one immutable user-message context for a planning decision."""

    request = UserMessageWorkspaceRequest(
        trigger=WorkspaceTrigger.USER_MESSAGE,
        url="https://www.linkedin.com/jobs/view/123",
        resourceUrl="https://www.linkedin.com/jobs/view/123",
        operationId="00000000-0000-0000-0000-000000000001",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        pageText="FULL PAGE BODY",
        imageText="COMPANY LOGO CLUE",
        intent="JOB PAGE INTENT",
        lang="en",
        actionId=action,
        histories=histories or [],
        artifacts=Artifacts(cv=None, cover_letter=None),
        message=message,
    )
    return JobChatContext(
        trigger=request.trigger,
        request=request,
        resume_text="# Canonical Resume\n\nREQUEST RESUME",
        histories=tuple(request.histories),
        artifacts=request.artifacts,
        selected_action=request.action_id,
        current_message=request.message,
    )


def async_completion(
    responses: list[str], captured: list[dict[str, str]] | None = None
) -> Callable[..., Awaitable[tuple[str, str]]]:
    """Return an awaited completion boundary with deterministic responses."""

    remaining = iter(responses)

    async def complete_prompt(*, system: str, prompt: str) -> tuple[str, str]:
        """Return the next prepared response and capture one planning call."""

        if captured is not None:
            captured.append({"system": system, "prompt": prompt})
        return next(remaining), "planner-model"

    return complete_prompt


def plan_result(specialist: SpecialistId, output_mode: OutputMode) -> str:
    """Serialize one structured chat plan for the fake completion boundary."""

    return json.dumps({"specialist": specialist, "output_mode": output_mode})


def test_current_message_outranks_selected_action() -> None:
    """Keep the current user message as the planner's strongest evidence."""

    captured: list[dict[str, str]] = []
    planner = ChatPlanner(
        complete_prompt=async_completion(
            [plan_result(SpecialistId.COVER_LETTER, OutputMode.ARTIFACT)], captured
        )
    )

    decision = asyncio.run(
        planner.plan(
            context(
                action=ActionId.TAILOR_RESUME,
                message="Write me a concise cover letter for this role.",
            )
        )
    )

    assert decision == ChatPlan(
        specialist=SpecialistId.COVER_LETTER,
        output_mode=OutputMode.ARTIFACT,
    )
    assert "current user message > selected Action > histories" in captured[0]["system"]
    assert "Write me a concise cover letter for this role." in captured[0]["prompt"]
    assert "Selected Action: tailor_resume" in captured[0]["prompt"]


def test_selected_action_is_a_strong_hint_but_does_not_force_artifact() -> None:
    """Allow an Action to select a Specialist while the message selects reply mode."""

    captured: list[dict[str, str]] = []
    planner = ChatPlanner(
        complete_prompt=async_completion(
            [plan_result(SpecialistId.RESUME, OutputMode.REPLY)], captured
        )
    )

    decision = asyncio.run(
        planner.plan(
            context(
                action=ActionId.TAILOR_RESUME,
                message="Which experience should I emphasize?",
                histories=[
                    HistoryMessage(
                        role="user",
                        content="Maybe write a cover letter later.",
                    )
                ],
            )
        )
    )

    assert decision.output_mode is OutputMode.REPLY
    assert "Selected Action: tailor_resume" in captured[0]["prompt"]
    assert "strong intent hint, not a forced Artifact command" in captured[0]["system"]
    assert "Maybe write a cover letter later." in captured[0]["prompt"]


def test_history_informs_follow_up_plan() -> None:
    """Expose complete history so the planner can resolve a vague rewrite request."""

    captured: list[dict[str, str]] = []
    planner = ChatPlanner(
        complete_prompt=async_completion(
            [plan_result(SpecialistId.COVER_LETTER, OutputMode.ARTIFACT)], captured
        )
    )

    decision = asyncio.run(
        planner.plan(
            context(
                message="Rewrite the previous one to sound more direct.",
                histories=[
                    HistoryMessage(role="user", content="Please write a cover letter."),
                    HistoryMessage(
                        role="assistant",
                        content="# Cover Letter\n\nDear Hiring Manager,",
                    ),
                ],
            )
        )
    )

    assert decision.specialist is SpecialistId.COVER_LETTER
    assert decision.output_mode is OutputMode.ARTIFACT
    assert "Rewrite the previous one to sound more direct." in captured[0]["prompt"]
    assert "# Cover Letter" in captured[0]["prompt"]


def test_general_qa_is_used_only_after_a_valid_model_plan() -> None:
    """Accept General QA only as an explicit legal structured plan."""

    planner = ChatPlanner(
        complete_prompt=async_completion(
            [plan_result(SpecialistId.GENERAL_QA, OutputMode.REPLY)]
        )
    )

    decision = asyncio.run(planner.plan(context(message="What does ATS mean?")))

    assert decision == ChatPlan(
        specialist=SpecialistId.GENERAL_QA,
        output_mode=OutputMode.REPLY,
    )


@pytest.mark.parametrize(
    ("specialist", "output_mode"),
    [
        (SpecialistId.JOB_ANALYSIS, OutputMode.REPLY),
        (SpecialistId.RESUME, OutputMode.REPLY),
        (SpecialistId.RESUME, OutputMode.ARTIFACT),
        (SpecialistId.COVER_LETTER, OutputMode.REPLY),
        (SpecialistId.COVER_LETTER, OutputMode.ARTIFACT),
        (SpecialistId.GENERAL_QA, OutputMode.REPLY),
    ],
)
def test_planner_accepts_legal_plans(
    specialist: SpecialistId,
    output_mode: OutputMode,
) -> None:
    """Accept every legal Specialist and output-mode combination."""

    raw = json.dumps({"specialist": specialist, "output_mode": output_mode})
    planner = ChatPlanner(complete_prompt=async_completion([raw]))

    decision = asyncio.run(planner.plan(context()))

    assert decision == ChatPlan(specialist=specialist, output_mode=output_mode)


def test_invalid_first_output_uses_exactly_one_repair_call() -> None:
    """Repair one invalid plan using the original context and required schema."""

    captured: list[dict[str, str]] = []
    planner = ChatPlanner(
        complete_prompt=async_completion(
            [
                "not valid JSON",
                plan_result(SpecialistId.RESUME, OutputMode.ARTIFACT),
            ],
            captured,
        )
    )

    decision = asyncio.run(planner.plan(context()))

    assert decision.specialist is SpecialistId.RESUME
    assert decision.output_mode is OutputMode.ARTIFACT
    assert len(captured) == 2
    assert "not valid JSON" in captured[1]["prompt"]
    assert '"output_mode"' in captured[1]["prompt"]


def test_planner_rejects_artifact_for_analysis_after_one_repair() -> None:
    """Reject Artifact mode for a reply-only Specialist after one repair."""

    invalid = '{"specialist":"job_analysis","output_mode":"artifact"}'
    planner = ChatPlanner(complete_prompt=async_completion([invalid, invalid]))

    with pytest.raises(ChatPlanningError, match="invalid structured chat plan"):
        asyncio.run(planner.plan(context()))


def test_planner_forbids_unknown_fields() -> None:
    """Reject model fields outside the exact plan schema."""

    invalid = json.dumps(
        {"specialist": "resume", "output_mode": "reply", "reason": "private"}
    )
    planner = ChatPlanner(complete_prompt=async_completion([invalid, invalid]))

    with pytest.raises(ChatPlanningError, match="invalid structured chat plan"):
        asyncio.run(planner.plan(context()))


def test_second_invalid_output_raises_bounded_error_without_model_text() -> None:
    """Expose a typed bounded error without leaking either raw model response."""

    planner = ChatPlanner(
        complete_prompt=async_completion(["SECRET FIRST OUTPUT", "SECRET SECOND OUTPUT"])
    )

    with pytest.raises(ChatPlanningError) as exc_info:
        asyncio.run(planner.plan(context()))

    assert str(exc_info.value) == "invalid structured chat plan"
    assert "SECRET" not in str(exc_info.value)
