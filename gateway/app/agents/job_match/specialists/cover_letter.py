"""Cover-letter Specialist Strategy."""

from app.agents.job_match.specialists.base import StructuredJobMatchSpecialist
from app.modules.task.schema import ArtifactType


class CoverLetterAgent(StructuredJobMatchSpecialist):
    """Answer cover-letter questions or produce one complete factual letter."""

    allowed_artifact_type = ArtifactType.COVER_LETTER
    scenario_instruction = (
        "Own the cover-letter scenario. Choose the result type from the actual current user "
        "request, not from the selected Action alone. An advice question, explanation "
        "request, or question about what to emphasize must return reply. Only an explicit "
        "create or rewrite instruction may return artifact_draft with artifact_type "
        "cover_letter. That draft must be the complete ready-to-send cover letter in "
        "Markdown, never suggestions or a partial patch, and every claim must remain "
        "grounded in the canonical resume."
    )


__all__ = ["CoverLetterAgent"]
