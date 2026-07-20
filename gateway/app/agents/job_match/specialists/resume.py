"""Resume-tailoring Specialist Strategy."""

from app.agents.job_match.planner import OutputMode
from app.agents.job_match.specialists.base import StreamingJobMatchSpecialist


class ResumeTailoringAgent(StreamingJobMatchSpecialist):
    """Answer resume questions or produce one complete, factual CV draft."""

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


__all__ = ["ResumeTailoringAgent"]
