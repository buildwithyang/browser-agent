"""General job-search Q&A Specialist Strategy."""

from app.agents.job_match.planner import OutputMode
from app.agents.job_match.specialists.base import StreamingJobMatchSpecialist


class GeneralQAAgent(StreamingJobMatchSpecialist):
    """Answer contextual job-search questions without creating Artifacts."""

    allowed_modes = frozenset({OutputMode.REPLY})
    reply_instruction = (
        "Own the general job-search question scenario. Return a concise, useful reply "
        "grounded in the supplied context."
    )


__all__ = ["GeneralQAAgent"]
