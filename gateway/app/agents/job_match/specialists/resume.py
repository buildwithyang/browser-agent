"""Resume-tailoring Specialist Strategy."""

from app.agents.job_match.context import JobChatContext
from app.agents.job_match.intent_router import OutputMode, SpecialistId
from app.agents.job_match.specialists.base import StreamingJobMatchSpecialist
from app.modules.task.schema import Artifact


class ResumeTailoringAgent(StreamingJobMatchSpecialist):
    """Answer resume questions or produce one complete, factual CV draft."""

    specialist_id = SpecialistId.RESUME
    description = (
        "Answer CV-tailoring questions and create or update a complete CV when the user "
        "explicitly requests a finished draft."
    )
    allowed_modes = frozenset({OutputMode.REPLY, OutputMode.ARTIFACT})
    reply_instruction = (
        "Own the resume-tailoring scenario. Answer the user's resume question with concrete "
        "advice grounded in the canonical resume and current role."
    )
    artifact_instruction = (
        "Own the resume-tailoring scenario. Produce the complete ATS-friendly CV in Markdown, "
        "never suggestions, a partial patch, or invented experience. Ground every claim in "
        "the canonical resume while tailoring emphasis to the current role."
    )

    def current_artifact(self, context: JobChatContext) -> Artifact | None:
        """Read only the current CV draft selected by the Workspace reducer."""

        return context.artifacts.cv


__all__ = ["ResumeTailoringAgent"]
