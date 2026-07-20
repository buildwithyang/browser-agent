"""Contract tests for stateless job-match intent routing."""

import json
from collections.abc import Callable
from uuid import uuid4

import pytest

from app.agents.job_match.context import JobChatContext
from app.agents.job_match.router import (
    IntentRouter,
    IntentRoutingError,
    SpecialistId,
)
from app.modules.task.schema import (
    ActionId,
    Artifact,
    ArtifactType,
    Artifacts,
    Attachment,
    HistoryMessage,
    UserMessageWorkspaceRequest,
    WorkspaceTrigger,
)


LONG_JD = (
    "Senior Backend Engineer responsible for distributed Go services, APIs, "
    "Kubernetes, observability, reliability, and cross-team architecture. "
) * 12


def _artifact(artifact_type: ArtifactType, draft: str) -> tuple[Artifact, Attachment]:
    """Build one valid Artifact and its latest immutable Attachment snapshot."""

    artifact_id = uuid4()
    attachment = Attachment(
        artifact_id=artifact_id,
        version=1,
        type=artifact_type,
        title="Current CV" if artifact_type is ArtifactType.CV else "Current Letter",
        content="https://example.com/cv.pdf" if artifact_type is ArtifactType.CV else draft,
    )
    return (
        Artifact(
            id=artifact_id,
            type=artifact_type,
            version=1,
            title=attachment.title,
            draft=draft,
            attachment=attachment,
        ),
        attachment,
    )


def _context(
    *,
    action: ActionId = ActionId.ASK_MORE,
    message: str = "What should I emphasize?",
    histories: list[HistoryMessage] | None = None,
) -> JobChatContext:
    """Build a complete user-message context for one routing decision."""

    cv, cv_attachment = _artifact(ArtifactType.CV, "# Existing CV\n\nCV SNAPSHOT")
    letter, letter_attachment = _artifact(
        ArtifactType.COVER_LETTER,
        "# Existing Cover Letter\n\nLETTER SNAPSHOT",
    )
    if histories is None:
        histories = [
            HistoryMessage(role="user", content="HISTORY USER QUESTION"),
            HistoryMessage(
                role="assistant",
                content="HISTORY ASSISTANT ANSWER",
                attachments=[cv_attachment],
            ),
            HistoryMessage(
                role="assistant",
                content="HISTORY LETTER ANSWER",
                attachments=[letter_attachment],
            ),
        ]
        artifacts = Artifacts(cv=cv, cover_letter=letter)
    else:
        artifacts = Artifacts(cv=None, cover_letter=None)
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
        histories=histories,
        artifacts=artifacts,
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


def _completion(
    responses: list[str], captured: list[dict[str, str]] | None = None
) -> Callable[..., tuple[str, str]]:
    """Return a deterministic injected completion boundary and capture its calls."""

    remaining = iter(responses)

    def complete_prompt(*, system: str, prompt: str) -> tuple[str, str]:
        """Return the next prepared model response for one classification call."""

        if captured is not None:
            captured.append({"system": system, "prompt": prompt})
        return next(remaining), "router-model"

    return complete_prompt


def _decision(specialist: SpecialistId) -> str:
    """Serialize one valid structured routing decision."""

    return json.dumps({"specialist": specialist.value})


def test_current_message_outranks_selected_action() -> None:
    """Expose the current-message-first rule to the structured classifier."""

    captured: list[dict[str, str]] = []
    decision = IntentRouter(
        complete_prompt=_completion([_decision(SpecialistId.COVER_LETTER)], captured)
    ).route(
        _context(
            action=ActionId.TAILOR_RESUME,
            message="Write me a concise cover letter for this role.",
        )
    )

    assert decision.specialist is SpecialistId.COVER_LETTER
    assert "current user message > selected Action > histories" in captured[0]["system"]
    assert "Write me a concise cover letter for this role." in captured[0]["prompt"]
    assert "tailor_resume" in captured[0]["prompt"]


def test_selected_action_outranks_ambiguous_history() -> None:
    """Expose the selected Action as the tie-breaker before vague history."""

    captured: list[dict[str, str]] = []
    decision = IntentRouter(
        complete_prompt=_completion([_decision(SpecialistId.JOB_ANALYSIS)], captured)
    ).route(
        _context(
            action=ActionId.ANALYZE,
            message="Can you help?",
            histories=[HistoryMessage(role="user", content="Maybe write a letter later.")],
        )
    )

    assert decision.specialist is SpecialistId.JOB_ANALYSIS
    assert "Selected Action: analyze" in captured[0]["prompt"]
    assert "Maybe write a letter later." in captured[0]["prompt"]


def test_history_informs_follow_up_pronouns_and_previous_rewrites() -> None:
    """Provide complete history so the model can resolve an otherwise vague follow-up."""

    captured: list[dict[str, str]] = []
    decision = IntentRouter(
        complete_prompt=_completion([_decision(SpecialistId.COVER_LETTER)], captured)
    ).route(
        _context(
            message="Rewrite the previous one to sound more direct.",
            histories=[
                HistoryMessage(role="user", content="Please write a cover letter."),
                HistoryMessage(role="assistant", content="# Cover Letter\n\nDear Hiring Manager,"),
            ],
        )
    )

    assert decision.specialist is SpecialistId.COVER_LETTER
    assert "Rewrite the previous one to sound more direct." in captured[0]["prompt"]
    assert "# Cover Letter" in captured[0]["prompt"]


def test_general_qa_is_used_only_after_a_valid_model_decision() -> None:
    """Accept General QA only as an explicit valid structured model choice."""

    decision = IntentRouter(
        complete_prompt=_completion([_decision(SpecialistId.GENERAL_QA)])
    ).route(_context(message="What does ATS mean?"))

    assert decision.specialist is SpecialistId.GENERAL_QA


def test_invalid_first_output_uses_exactly_one_repair_call() -> None:
    """Repair one invalid classification using its raw output and required schema."""

    captured: list[dict[str, str]] = []
    decision = IntentRouter(
        complete_prompt=_completion(
            ["not valid JSON", _decision(SpecialistId.RESUME)], captured
        )
    ).route(_context())

    assert decision.specialist is SpecialistId.RESUME
    assert len(captured) == 2
    assert "not valid JSON" in captured[1]["prompt"]
    assert '"specialist"' in captured[1]["prompt"]


def test_second_invalid_output_raises_typed_routing_error() -> None:
    """Reject two invalid outputs instead of silently choosing General QA."""

    router = IntentRouter(complete_prompt=_completion(["{}", "[]"]))

    with pytest.raises(IntentRoutingError, match="invalid structured routing decision"):
        router.route(_context())


def test_router_never_requests_reply_or_artifact_decisions() -> None:
    """Constrain the classifier prompt to one Specialist identifier only."""

    captured: list[dict[str, str]] = []
    IntentRouter(
        complete_prompt=_completion([_decision(SpecialistId.RESUME)], captured)
    ).route(_context())

    assert '"specialist"' in captured[0]["system"]
    assert '"type"' not in captured[0]["system"]
    assert "create_artifact" not in captured[0]["system"]
    assert "update_artifact" not in captured[0]["system"]
