"""Contract tests for asynchronous job-match intent routing."""

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest

from app.agents.job_match.context import JobChatContext
from app.agents.job_match.intent_router import (
    IntentRouter,
    IntentRoutingError,
    OutputMode,
    RoutingDecision,
    SpecialistId,
)
from app.modules.task.schema import (
    Artifact,
    ArtifactType,
    Artifacts,
    Attachment,
    HistoryMessage,
    WorkspaceRequest,
)


LONG_JD = (
    "Senior Backend Engineer responsible for distributed Go services, APIs, "
    "Kubernetes, observability, reliability, and cross-team architecture. "
) * 12


class RoutingSpecialistStub:
    """Expose only the Specialist metadata consumed by IntentRouter."""

    def __init__(
        self,
        specialist_id: str,
        description: str,
        allowed_modes: frozenset[OutputMode],
    ) -> None:
        """Store one dynamic routing capability."""

        self.specialist_id = specialist_id
        self.description = description
        self.allowed_modes = allowed_modes


def _routing_specialists() -> dict[str, RoutingSpecialistStub]:
    """Build the four production-like capabilities used by Router contract tests."""

    return {
        SpecialistId.JOB_ANALYSIS: RoutingSpecialistStub(
            SpecialistId.JOB_ANALYSIS,
            "Analyze the role and candidate fit.",
            frozenset({OutputMode.REPLY}),
        ),
        SpecialistId.RESUME: RoutingSpecialistStub(
            SpecialistId.RESUME,
            "Answer CV questions or create a complete CV.",
            frozenset({OutputMode.REPLY, OutputMode.ARTIFACT}),
        ),
        SpecialistId.COVER_LETTER: RoutingSpecialistStub(
            SpecialistId.COVER_LETTER,
            "Answer cover-letter questions or create a complete letter.",
            frozenset({OutputMode.REPLY, OutputMode.ARTIFACT}),
        ),
        SpecialistId.GENERAL_QA: RoutingSpecialistStub(
            SpecialistId.GENERAL_QA,
            "Answer other contextual questions.",
            frozenset({OutputMode.REPLY}),
        ),
    }


def _router(
    *,
    complete_prompt: Callable[..., Awaitable[tuple[str, str]]],
    specialists: dict[str, RoutingSpecialistStub] | None = None,
) -> IntentRouter:
    """Build an IntentRouter with explicit test capabilities."""

    return IntentRouter(
        complete_prompt=complete_prompt,
        specialists=(
            specialists if specialists is not None else _routing_specialists()
        ),
    )


def test_intent_router_accepts_specialist_map() -> None:
    """Make the Router the sole owner of registered Specialist instances."""

    assert "specialists" in inspect.signature(IntentRouter).parameters


def test_routing_decision_accepts_registered_string_id() -> None:
    """Allow new Specialist IDs without editing a closed Python enum."""

    assert RoutingDecision.model_fields["specialist"].annotation is str


def test_router_builds_candidates_from_specialist_map() -> None:
    """Expose only currently registered Specialist capabilities to the model."""

    summary = RoutingSpecialistStub(
        "summary",
        "Summarize the current page and extract its key points.",
        frozenset({OutputMode.REPLY}),
    )
    captured: list[dict[str, str]] = []
    router = _router(
        complete_prompt=async_completion(
            [route_result("summary", OutputMode.REPLY)],
            captured,
        ),
        specialists={"summary": summary},
    )

    decision = asyncio.run(router.route(context(message="Summarize this page.")))

    assert decision.specialist == "summary"
    assert '"id": "summary"' in captured[0]["system"]
    assert "Summarize the current page and extract its key points." in captured[0][
        "system"
    ]
    assert '"id": "resume"' not in captured[0]["system"]


def test_router_resolves_registered_specialist() -> None:
    """Return the same Specialist instance stored in the Router map."""

    summary = RoutingSpecialistStub(
        "summary",
        "Summarize the current page.",
        frozenset({OutputMode.REPLY}),
    )
    router = _router(
        complete_prompt=async_completion([]),
        specialists={"summary": summary},
    )

    assert callable(getattr(router, "resolve_specialist", None))
    assert router.resolve_specialist("summary") is summary


@pytest.mark.parametrize(
    ("specialist_id", "output_mode"),
    [
        ("missing", OutputMode.REPLY),
        ("summary", OutputMode.ARTIFACT),
    ],
)
def test_router_rejects_decisions_outside_registered_capabilities(
    specialist_id: str,
    output_mode: OutputMode,
) -> None:
    """Reject unknown IDs and output modes not supported by the selected Specialist."""

    summary = RoutingSpecialistStub(
        "summary",
        "Summarize the current page.",
        frozenset({OutputMode.REPLY}),
    )
    router = _router(
        complete_prompt=async_completion(
            [
                route_result(specialist_id, output_mode),
                route_result(specialist_id, output_mode),
            ]
        ),
        specialists={"summary": summary},
    )

    with pytest.raises(IntentRoutingError, match="invalid structured intent route"):
        asyncio.run(router.route(context()))


def context(
    *,
    message: str = "What should I emphasize?",
    histories: list[HistoryMessage] | None = None,
    artifacts: Artifacts | None = None,
) -> JobChatContext:
    """Build one immutable user-message context for a planning decision."""

    request = WorkspaceRequest(
        url="https://www.linkedin.com/jobs/view/123",
        resourceUrl="https://www.linkedin.com/jobs/view/123",
        operationId="00000000-0000-0000-0000-000000000001",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        pageText="FULL PAGE BODY",
        imageText="COMPANY LOGO CLUE",
        intent="JOB PAGE INTENT",
        lang="en",
        histories=histories or [],
        artifacts=artifacts or Artifacts(cv=None, cover_letter=None),
        message=message,
    )
    return JobChatContext(
        request=request,
        resume_text="# Canonical Resume\n\nREQUEST RESUME",
        histories=tuple(request.histories),
        artifacts=request.artifacts,
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


def route_result(
    specialist: str,
    output_mode: OutputMode,
    instruction: str = "Fulfill the current user request exactly.",
) -> str:
    """Serialize one structured routing decision for the fake completion boundary."""

    return json.dumps(
        {
            "specialist": specialist,
            "output_mode": output_mode,
            "instruction": instruction,
        }
    )


def test_current_message_outranks_current_artifacts_and_histories() -> None:
    """Keep the current user message as the planner's strongest evidence."""

    captured: list[dict[str, str]] = []
    router = _router(
        complete_prompt=async_completion(
            [
                route_result(
                    SpecialistId.COVER_LETTER,
                    OutputMode.ARTIFACT,
                    "Write the requested concise cover letter.",
                )
            ],
            captured,
        )
    )

    decision = asyncio.run(
        router.route(
            context(
                message="Write me a concise cover letter for this role.",
            )
        )
    )

    assert decision == RoutingDecision(
        specialist=SpecialistId.COVER_LETTER,
        output_mode=OutputMode.ARTIFACT,
        instruction="Write the requested concise cover letter.",
    )
    assert (
        "current message > current artifacts > histories"
        in captured[0]["system"]
    )
    assert "Write me a concise cover letter for this role." in captured[0]["prompt"]
    prompt = captured[0]["prompt"]
    assert prompt.index("# Current user message") < prompt.index(
        "# Current artifact metadata"
    )
    assert prompt.index("# Current artifact metadata") < prompt.index(
        "# Recent conversation text"
    )


def test_resume_advice_message_can_select_reply_mode() -> None:
    """Allow the current message to select a resume reply without routing metadata."""

    captured: list[dict[str, str]] = []
    router = _router(
        complete_prompt=async_completion(
            [route_result(SpecialistId.RESUME, OutputMode.REPLY)], captured
        )
    )

    decision = asyncio.run(
        router.route(
            context(
                message="Which experience should I emphasize?",
                histories=[
                    HistoryMessage(
                        role="user",
                        content="Maybe write a cover letter later.",
                    ),
                    HistoryMessage(
                        role="assistant",
                        content="We can decide after reviewing your experience.",
                    ),
                ],
            )
        )
    )

    assert decision.output_mode is OutputMode.REPLY
    assert "Selected Action" not in captured[0]["prompt"]
    assert "Maybe write a cover letter later." in captured[0]["prompt"]


def test_recent_text_history_informs_follow_up_route() -> None:
    """Expose recent text so the router can resolve a vague rewrite request."""

    captured: list[dict[str, str]] = []
    router = _router(
        complete_prompt=async_completion(
            [route_result(SpecialistId.COVER_LETTER, OutputMode.ARTIFACT)], captured
        )
    )

    decision = asyncio.run(
        router.route(
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

    assert decision.specialist == SpecialistId.COVER_LETTER
    assert decision.output_mode is OutputMode.ARTIFACT
    assert "Rewrite the previous one to sound more direct." in captured[0]["prompt"]
    assert "# Cover Letter" in captured[0]["prompt"]


def test_existing_cover_letter_edit_is_explicitly_planned_as_artifact() -> None:
    """Expose the current Artifact and classify an elliptical direct edit as an update."""

    artifact_id = uuid4()
    attachment = Attachment(
        artifact_id=artifact_id,
        version=1,
        type=ArtifactType.COVER_LETTER,
        title="Cover Letter",
        content="Dear Hiring Team,\n\nExisting complete letter.",
    )
    artifact = Artifact(
        id=artifact_id,
        type=ArtifactType.COVER_LETTER,
        version=1,
        title=attachment.title,
        draft=attachment.content,
        attachment=attachment,
    )
    histories = [
        HistoryMessage(
            role="user",
            content="请生成求职信。",
        ),
        HistoryMessage(
            role="assistant",
            content="已创建求职信。",
            attachments=[attachment],
        )
    ]
    captured: list[dict[str, str]] = []
    router = _router(
        complete_prompt=async_completion(
            [route_result(SpecialistId.COVER_LETTER, OutputMode.ARTIFACT)],
            captured,
        )
    )

    decision = asyncio.run(
        router.route(
            context(
                message="生成的简短一点。",
                histories=histories,
                artifacts=Artifacts(cv=None, cover_letter=artifact),
            )
        )
    )

    assert decision == RoutingDecision(
        specialist=SpecialistId.COVER_LETTER,
        output_mode=OutputMode.ARTIFACT,
        instruction="Fulfill the current user request exactly.",
    )
    assert "direct edit or transformation" in captured[0]["system"]
    assert "make it shorter" in captured[0]["system"]
    assert "# Current artifact metadata" in captured[0]["prompt"]
    assert "Existing complete letter." not in captured[0]["prompt"]
    assert '"title": "Cover Letter"' in captured[0]["prompt"]


def test_general_qa_is_used_only_after_a_valid_model_plan() -> None:
    """Accept General QA only as an explicit legal structured plan."""

    router = _router(
        complete_prompt=async_completion(
            [route_result(SpecialistId.GENERAL_QA, OutputMode.REPLY)]
        )
    )

    decision = asyncio.run(router.route(context(message="What does ATS mean?")))

    assert decision == RoutingDecision(
        specialist=SpecialistId.GENERAL_QA,
        output_mode=OutputMode.REPLY,
        instruction="Fulfill the current user request exactly.",
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
def test_router_accepts_legal_decisions(
    specialist: SpecialistId,
    output_mode: OutputMode,
) -> None:
    """Accept every legal Specialist and output-mode combination."""

    raw = route_result(specialist, output_mode)
    router = _router(complete_prompt=async_completion([raw]))

    decision = asyncio.run(router.route(context()))

    assert decision == RoutingDecision(
        specialist=specialist,
        output_mode=output_mode,
        instruction="Fulfill the current user request exactly.",
    )


def test_invalid_first_output_uses_exactly_one_repair_call() -> None:
    """Repair one invalid plan using the original context and required schema."""

    captured: list[dict[str, str]] = []
    router = _router(
        complete_prompt=async_completion(
            [
                "not valid JSON",
                route_result(SpecialistId.RESUME, OutputMode.ARTIFACT),
            ],
            captured,
        )
    )

    decision = asyncio.run(router.route(context()))

    assert decision.specialist == SpecialistId.RESUME
    assert decision.output_mode is OutputMode.ARTIFACT
    assert len(captured) == 2
    assert "not valid JSON" in captured[1]["prompt"]
    assert '"output_mode"' in captured[1]["prompt"]


def test_router_rejects_artifact_for_analysis_after_one_repair() -> None:
    """Reject Artifact mode for a reply-only Specialist after one repair."""

    invalid = route_result(SpecialistId.JOB_ANALYSIS, OutputMode.ARTIFACT)
    router = _router(complete_prompt=async_completion([invalid, invalid]))

    with pytest.raises(IntentRoutingError, match="invalid structured intent route"):
        asyncio.run(router.route(context()))


def test_router_forbids_unknown_fields() -> None:
    """Reject model fields outside the exact plan schema."""

    invalid = json.dumps(
        {
            "specialist": "resume",
            "output_mode": "reply",
            "instruction": "Answer the question.",
            "reason": "private",
        }
    )
    router = _router(complete_prompt=async_completion([invalid, invalid]))

    with pytest.raises(IntentRoutingError, match="invalid structured intent route"):
        asyncio.run(router.route(context()))


def test_router_rejects_blank_specialist_instruction() -> None:
    """Require a meaningful handoff rather than whitespace-only model output."""

    invalid = route_result(SpecialistId.RESUME, OutputMode.REPLY, "   ")
    router = _router(complete_prompt=async_completion([invalid, invalid]))

    with pytest.raises(IntentRoutingError, match="invalid structured intent route"):
        asyncio.run(router.route(context()))


def test_second_invalid_output_raises_bounded_error_without_model_text() -> None:
    """Expose a typed bounded error without leaking either raw model response."""

    router = _router(
        complete_prompt=async_completion(["SECRET FIRST OUTPUT", "SECRET SECOND OUTPUT"])
    )

    with pytest.raises(IntentRoutingError) as exc_info:
        asyncio.run(router.route(context()))

    assert str(exc_info.value) == "invalid structured intent route"
    assert "SECRET" not in str(exc_info.value)


def test_router_preserves_exact_user_literals_in_specialist_instruction() -> None:
    """Require the handoff to retain proper names and other user-provided literals."""

    captured: list[dict[str, str]] = []
    router = _router(
        complete_prompt=async_completion(
            [
                route_result(
                    SpecialistId.COVER_LETTER,
                    OutputMode.ARTIFACT,
                    "将求职信中的候选人姓名准确更新为 Yang Yu。",
                )
            ],
            captured,
        )
    )

    decision = asyncio.run(router.route(context(message="把名字改成 Yang Yu")))

    assert decision.instruction.endswith("Yang Yu。")
    assert "preserve exact user-provided literals" in captured[0]["system"]


def test_router_uses_recent_text_and_artifact_metadata_only() -> None:
    """Keep drafts and historical Attachments out of the routing prompt."""

    artifact_id = uuid4()
    attachment = Attachment(
        artifact_id=artifact_id,
        version=3,
        type=ArtifactType.COVER_LETTER,
        title="Latest Letter",
        content="HISTORICAL ATTACHMENT SECRET",
    )
    artifact = Artifact(
        id=artifact_id,
        type=ArtifactType.COVER_LETTER,
        version=3,
        title="Latest Letter",
        draft="CURRENT DRAFT SECRET",
        attachment=attachment,
    )
    histories = [
        HistoryMessage(role="user", content="TOO OLD MESSAGE"),
        HistoryMessage(role="assistant", content="TOO OLD ANSWER"),
        HistoryMessage(role="user", content="RECENT TEXT 1"),
        HistoryMessage(role="assistant", content="RECENT TEXT 2"),
        HistoryMessage(role="user", content="RECENT TEXT 3"),
        HistoryMessage(role="assistant", content="RECENT TEXT 4"),
    ]
    histories[-1] = HistoryMessage(
        role="assistant",
        content="RECENT TEXT 4",
        attachments=[attachment],
    )
    captured: list[dict[str, str]] = []
    router = _router(
        complete_prompt=async_completion(
            [route_result(SpecialistId.COVER_LETTER, OutputMode.ARTIFACT)],
            captured,
        )
    )

    asyncio.run(
        router.route(
            context(
                histories=histories,
                artifacts=Artifacts(cv=None, cover_letter=artifact),
            )
        )
    )

    prompt = captured[0]["prompt"]
    assert "TOO OLD MESSAGE" not in prompt
    assert "TOO OLD ANSWER" not in prompt
    for index in range(1, 5):
        assert f"RECENT TEXT {index}" in prompt
    assert "CURRENT DRAFT SECRET" not in prompt
    assert "HISTORICAL ATTACHMENT SECRET" not in prompt
    assert '"title": "Latest Letter"' in prompt
    assert '"version": 3' in prompt
