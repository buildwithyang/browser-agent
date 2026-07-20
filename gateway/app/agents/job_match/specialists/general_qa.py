"""General job-search Q&A Specialist Strategy."""

from app.agents.job_match.specialists.base import StructuredJobMatchSpecialist


class GeneralQAAgent(StructuredJobMatchSpecialist):
    """Answer contextual job-search questions without creating Artifacts."""

    scenario_instruction = (
        "Own the general job-search question scenario. Always return a concise, useful "
        "reply grounded in the supplied context and never return an artifact draft."
    )


__all__ = ["GeneralQAAgent"]
