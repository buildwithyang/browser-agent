"""Cover-letter Specialist Strategy."""

from app.agents.job_match.context import JobChatContext
from app.agents.job_match.intent_router import OutputMode, SpecialistId
from app.agents.job_match.specialists.base import StreamingJobMatchSpecialist
from app.modules.task.schema import Artifact


class CoverLetterAgent(StreamingJobMatchSpecialist):
    """Answer cover-letter questions or produce one complete factual letter."""

    specialist_id = SpecialistId.COVER_LETTER
    description = (
        "Answer cover-letter questions and create or update a complete cover letter when "
        "the user explicitly requests a finished draft."
    )
    allowed_modes = frozenset({OutputMode.REPLY, OutputMode.ARTIFACT})
    reply_instruction = (
        "Own the cover-letter scenario. Answer the user's cover-letter question with concrete "
        "advice grounded in the canonical resume and current role."
    )
    artifact_instruction = (
        "Own the cover-letter scenario. Produce the complete ready-to-send cover letter in "
        "plain text, never suggestions, a partial patch, or invented experience. Ground every "
        "claim in the canonical resume while addressing the current role."
    )
    artifact_output_instruction = (
        "Return only the complete copy-ready plain text cover letter. Do not add commentary, "
        "a completion note, transport metadata, or Markdown syntax such as headings, lists, "
        "emphasis, horizontal rules, links, or code fences. Preserve readable paragraphs."
    )

    def current_artifact(self, context: JobChatContext) -> Artifact | None:
        """Read only the current cover-letter draft selected by the Workspace reducer."""

        return context.artifacts.cover_letter


__all__ = ["CoverLetterAgent"]
