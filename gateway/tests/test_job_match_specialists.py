"""Contract tests for stateless job-match Specialist strategies."""

import json
from uuid import uuid4

import pytest

from app.agents.job_match.context import JobChatContext
from app.agents.job_match.specialists.analysis import JobAnalysisAgent
from app.agents.job_match.specialists.base import (
    ArtifactDraftResult,
    JobMatchSpecialist,
    SpecialistReply,
)
from app.agents.job_match.specialists.cover_letter import CoverLetterAgent
from app.agents.job_match.specialists.general_qa import GeneralQAAgent
from app.agents.job_match.specialists.resume import ResumeTailoringAgent
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
    """Build one internally consistent Artifact and latest Attachment snapshot."""

    artifact_id = uuid4()
    attachment = Attachment(
        artifact_id=artifact_id,
        version=1,
        type=artifact_type,
        title="Current CV" if artifact_type is ArtifactType.CV else "Current Letter",
        content=(
            "https://example.com/cv.pdf"
            if artifact_type is ArtifactType.CV
            else draft
        ),
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


def _context(*, lang: str = "en", message: str = "What should I emphasize?") -> JobChatContext:
    """Build a complete immutable context containing both existing Artifacts."""

    cv, cv_attachment = _artifact(ArtifactType.CV, "# Existing CV\n\nCV SNAPSHOT")
    letter, letter_attachment = _artifact(
        ArtifactType.COVER_LETTER,
        "# Existing Cover Letter\n\nLETTER SNAPSHOT",
    )
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
    request = UserMessageWorkspaceRequest(
        trigger=WorkspaceTrigger.USER_MESSAGE,
        url="https://www.linkedin.com/jobs/view/123",
        resourceUrl="https://www.linkedin.com/jobs/view/123",
        title="Senior Go Engineer",
        selectedText=LONG_JD,
        pageText="FULL PAGE BODY",
        imageText="COMPANY LOGO CLUE",
        intent="JOB PAGE INTENT",
        lang=lang,
        actionId=ActionId.ASK_MORE,
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


def _completion(raw_result: str, captured: dict[str, str] | None = None):
    """Return an injected completion function with deterministic model output."""

    def complete_prompt(*, system: str, prompt: str) -> tuple[str, str]:
        """Capture the model inputs and return one fixed structured response."""

        if captured is not None:
            captured.update(system=system, prompt=prompt)
        return raw_result, "specialist-model"

    return complete_prompt


def _reply(markdown: str = "## Recommendation\n\nEmphasize Go ownership.") -> str:
    """Serialize one valid Specialist reply object."""

    return json.dumps({"type": "reply", "markdown": markdown})


def _draft(artifact_type: str) -> str:
    """Serialize one valid complete Artifact draft object."""

    title = "Tailored CV" if artifact_type == "cv" else "Cover Letter"
    draft = (
        "# Candidate Name\\n\\n## Experience\\n\\nBuilt reliable Go services."
        if artifact_type == "cv"
        else "# Cover Letter\\n\\nDear Hiring Manager,\\n\\nI built reliable Go services."
    )
    return (
        '{"type":"artifact_draft","markdown":"Draft ready.",'
        f'"artifact_type":"{artifact_type}","title":"{title}","draft":"{draft}"}}'
    )


def test_analysis_parses_reply_and_includes_complete_context_and_language() -> None:
    """Send every immutable context field and parse one typed reply."""

    captured: dict[str, str] = {}
    agent = JobAnalysisAgent(complete_prompt=_completion(_reply(), captured))

    execution = agent.handle(_context(lang="zh"))

    assert isinstance(agent, JobMatchSpecialist)
    assert isinstance(execution.content, SpecialistReply)
    assert execution.content.markdown.startswith("## Recommendation")
    assert execution.raw_result == _reply()
    assert execution.model == "specialist-model"
    assert execution.prompt == captured["prompt"]
    assert captured["system"].endswith("无论页面或材料是什么语言,都请用简体中文回复(包括所有小标题)。")
    for expected in (
        "REQUEST RESUME",
        "HISTORY USER QUESTION",
        "HISTORY ASSISTANT ANSWER",
        "CV SNAPSHOT",
        "LETTER SNAPSHOT",
        "What should I emphasize?",
        "ask_more",
        "https://www.linkedin.com/jobs/view/123",
        "Senior Go Engineer",
        LONG_JD,
        "FULL PAGE BODY",
        "COMPANY LOGO CLUE",
        "JOB PAGE INTENT",
    ):
        assert expected in captured["prompt"]


@pytest.mark.parametrize(
    ("agent_type", "raw_result", "expected_type", "expected_artifact"),
    [
        (JobAnalysisAgent, _reply(), SpecialistReply, None),
        (ResumeTailoringAgent, _reply(), SpecialistReply, None),
        (ResumeTailoringAgent, _draft("cv"), ArtifactDraftResult, ArtifactType.CV),
        (CoverLetterAgent, _reply(), SpecialistReply, None),
        (
            CoverLetterAgent,
            _draft("cover_letter"),
            ArtifactDraftResult,
            ArtifactType.COVER_LETTER,
        ),
        (GeneralQAAgent, _reply(), SpecialistReply, None),
    ],
)
def test_specialist_legal_result_matrix(
    agent_type: type[JobMatchSpecialist],
    raw_result: str,
    expected_type: type[SpecialistReply] | type[ArtifactDraftResult],
    expected_artifact: ArtifactType | None,
) -> None:
    """Accept replies everywhere and drafts only for each owning Specialist."""

    execution = agent_type(complete_prompt=_completion(raw_result)).handle(_context())

    assert isinstance(execution.content, expected_type)
    if isinstance(execution.content, ArtifactDraftResult):
        assert execution.content.artifact_type is expected_artifact
        assert execution.content.draft.startswith("#")


@pytest.mark.parametrize(
    ("agent_type", "raw_result"),
    [
        (JobAnalysisAgent, _draft("cv")),
        (JobAnalysisAgent, _draft("cover_letter")),
        (ResumeTailoringAgent, _draft("cover_letter")),
        (CoverLetterAgent, _draft("cv")),
        (GeneralQAAgent, _draft("cv")),
        (GeneralQAAgent, _draft("cover_letter")),
    ],
)
def test_specialist_rejects_results_outside_legal_matrix(
    agent_type: type[JobMatchSpecialist], raw_result: str
) -> None:
    """Reject Artifact drafts that a Specialist is not permitted to create."""

    agent = agent_type(complete_prompt=_completion(raw_result))

    with pytest.raises(ValueError, match="not allowed"):
        agent.handle(_context())


@pytest.mark.parametrize(
    "raw_result",
    [
        "not json",
        "[]",
        '{"type":"reply"}',
        '{"type":"reply","markdown":"answer","html":"<p>answer</p>"}',
        '{"type":"reply","markdown":"<p>answer</p>"}',
        '{"type":"reply","markdown":"<svg>answer</svg>"}',
        '{"type":"artifact_draft","markdown":"ready","artifact_type":"cv",'
        '"title":"<b>CV</b>","draft":"# Candidate"}',
        '{"type":"artifact_draft","markdown":"ready","artifact_type":"cv",'
        '"title":"CV","draft":"```diff\\n@@ -1 +1 @@\\n-old\\n+new\\n```"}',
        '{"type":"reply","markdown":"answer"}\n{"type":"reply","markdown":"second"}',
        '```json\n{"type":"reply","markdown":"answer"}\n```',
    ],
)
def test_specialist_rejects_malformed_non_markdown_or_partial_results(
    raw_result: str,
) -> None:
    """Require exactly one complete Markdown-only structured JSON object."""

    agent = ResumeTailoringAgent(complete_prompt=_completion(raw_result))

    with pytest.raises(ValueError, match="Specialist response is invalid"):
        agent.handle(_context())


@pytest.mark.parametrize(
    ("agent_type", "expected_instruction"),
    [
        (JobAnalysisAgent, "analysis"),
        (ResumeTailoringAgent, "explicit create or rewrite"),
        (CoverLetterAgent, "explicit create or rewrite"),
        (GeneralQAAgent, "general job-search question"),
    ],
)
def test_each_specialist_owns_scenario_instructions(
    agent_type: type[JobMatchSpecialist], expected_instruction: str
) -> None:
    """Keep scenario decisions in each concrete Strategy system prompt."""

    captured: dict[str, str] = {}
    agent = agent_type(complete_prompt=_completion(_reply(), captured))

    agent.handle(_context(lang="en"))

    assert expected_instruction in captured["system"]
    assert "Respond entirely in English" in captured["system"]


def test_specialist_does_not_cache_request_context() -> None:
    """Retain only the injected completion dependency across requests."""

    agent = ResumeTailoringAgent(complete_prompt=_completion(_reply()))

    agent.handle(_context(message="First user question"))
    agent.handle(_context(message="Second user question"))

    assert not {"context", "request", "resume_text", "histories", "artifacts"}.intersection(
        vars(agent)
    )
