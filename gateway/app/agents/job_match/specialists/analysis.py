"""Job analysis Specialist Strategy."""

from app.agents.job_match.intent_router import OutputMode, SpecialistId
from app.agents.job_match.specialists.base import StreamingJobMatchSpecialist


class JobAnalysisAgent(StreamingJobMatchSpecialist):
    """Answer with candid, evidence-based job and candidate analysis only."""

    specialist_id = SpecialistId.JOB_ANALYSIS
    description = (
        "Analyze job requirements, candidate strengths, core gaps, application risks, "
        "and whether the role is worth applying for."
    )
    allowed_modes = frozenset({OutputMode.REPLY})
    reply_instruction = (
        "Own the job analysis scenario. Return a conversational analysis reply. "
        "First compare every material requirement against the candidate in one Markdown "
        "table with exactly two comparison columns. For Chinese, use exactly "
        "'| JD 要求 | 匹配情况 |' followed by '| --- | --- |'. For English, use exactly "
        "'| JD Requirement | Match |' followed by '| --- | --- |'. Do not add any other "
        "comparison columns. After the table, narratively summarize strengths, core gaps, "
        "realistic fit, application risks, and a clear apply recommendation with reasons."
    )


__all__ = ["JobAnalysisAgent"]
