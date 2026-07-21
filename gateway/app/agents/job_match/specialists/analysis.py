"""Job analysis Specialist Strategy."""

from app.agents.job_match.planner import OutputMode
from app.agents.job_match.specialists.base import StreamingJobMatchSpecialist


class JobAnalysisAgent(StreamingJobMatchSpecialist):
    """Answer with candid, evidence-based job and candidate analysis only."""

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
