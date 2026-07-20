"""Job analysis Specialist Strategy."""

from app.agents.job_match.specialists.base import StructuredJobMatchSpecialist


class JobAnalysisAgent(StructuredJobMatchSpecialist):
    """Answer with candid, evidence-based job and candidate analysis only."""

    scenario_instruction = (
        "Own the job analysis scenario. Always return a reply, never an artifact draft. "
        "Analyze the role, hard requirements, strengths, gaps, realistic fit, application "
        "risks, and concrete next steps from the supplied evidence."
    )


__all__ = ["JobAnalysisAgent"]
