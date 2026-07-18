from __future__ import annotations

from urllib.parse import urlparse

from app.agents.job_match import MIN_JOB_CONTENT_CHARS
from app.modules.task.schema import AgentName, PageContext


def _is_linkedin_host(host: str) -> bool:
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _is_indeed_host(host: str) -> bool:
    return host == "indeed.com" or host.endswith(".indeed.com")


def route_browser_task(task: PageContext) -> AgentName:
    parsed = urlparse(task.url)
    host = (parsed.hostname or "").lower()
    has_full_jd = len(task.selected_text.strip()) >= MIN_JOB_CONTENT_CHARS
    is_supported_host = _is_linkedin_host(host) or _is_indeed_host(host)
    return (
        AgentName.JOB_MATCH
        if is_supported_host and has_full_jd
        else AgentName.SUMMARY_PAGE
    )
