"""General job-search Q&A Specialist Strategy."""

from app.agents.job_match.intent_router import OutputMode, SpecialistId
from app.agents.job_match.specialists.base import StreamingJobMatchSpecialist


class GeneralQAAgent(StreamingJobMatchSpecialist):
    """Answer contextual job-search questions without creating Artifacts."""

    specialist_id = SpecialistId.GENERAL_QA
    description = (
        "Answer open job-search questions that do not belong to job analysis, CV tailoring, "
        "or cover-letter work."
    )
    allowed_modes = frozenset({OutputMode.REPLY})
    reply_instruction = (
        "Own the general job-search question scenario. Return a concise, useful reply "
        "grounded in the supplied context."
    )


__all__ = ["GeneralQAAgent"]
