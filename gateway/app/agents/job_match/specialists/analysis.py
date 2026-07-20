"""Job analysis Specialist Strategy."""

from app.agents.job_match.planner import OutputMode
from app.agents.job_match.specialists.base import StreamingJobMatchSpecialist


class JobAnalysisAgent(StreamingJobMatchSpecialist):
    """Answer with candid, evidence-based job and candidate analysis only."""

    allowed_modes = frozenset({OutputMode.REPLY})
    reply_instruction = (
        "Own the job analysis scenario. Return a conversational analysis reply. "
        "Analyze the role, hard requirements, strengths, gaps, realistic fit, application "
        "risks, and concrete next steps from the supplied evidence."
    )


__all__ = ["JobAnalysisAgent"]
