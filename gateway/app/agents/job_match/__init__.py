"""Public job-match Agent package surface."""

from app.agents.job_match.agent import JobMatchAgent
from app.agents.job_match.quick_insight import MIN_JOB_CONTENT_CHARS

__all__ = ["JobMatchAgent", "MIN_JOB_CONTENT_CHARS"]
