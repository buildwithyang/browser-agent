"""Resume-tailoring Specialist Strategy."""

from app.agents.job_match.specialists.base import StructuredJobMatchSpecialist
from app.modules.task.schema import ArtifactType


class ResumeTailoringAgent(StructuredJobMatchSpecialist):
    """Answer resume questions or produce one complete, factual CV draft."""

    allowed_artifact_type = ArtifactType.CV
    scenario_instruction = (
        "Own the resume-tailoring scenario. If the user asks for advice, explanation, or "
        "what to emphasize, return a reply. Only an explicit create or rewrite instruction "
        "may return artifact_draft with artifact_type cv. That draft must be the complete "
        "ATS-friendly CV in Markdown, never suggestions or a partial patch, and every claim "
        "must remain grounded in the canonical resume."
    )


__all__ = ["ResumeTailoringAgent"]
