from __future__ import annotations

from typing import Literal
from urllib.parse import parse_qs, urlparse

from app.agents.job_match import MIN_JOB_CONTENT_CHARS
from app.modules.task.schema import TaskCreate

RoutedAgent = Literal["job_match", "summary_page"]


def _is_linkedin_job(host: str, path: str) -> bool:
    is_linkedin = host == "linkedin.com" or host.endswith(".linkedin.com")
    path_parts = path.strip("/").split("/")
    return (
        is_linkedin
        and len(path_parts) == 3
        and path_parts[:2] == ["jobs", "view"]
        and bool(path_parts[2])
    )


def _is_indeed_job(host: str, path: str, query: str) -> bool:
    is_indeed = host == "indeed.com" or host.endswith(".indeed.com")
    query_params = parse_qs(query)
    has_job_key = any(value for value in query_params.get("jk", []))
    return is_indeed and (path.rstrip("/") == "/viewjob" or has_job_key)


def route_browser_task(task: TaskCreate) -> RoutedAgent:
    parsed = urlparse(task.url)
    host = (parsed.hostname or "").lower()
    has_full_jd = len(task.selected_text.strip()) >= MIN_JOB_CONTENT_CHARS
    is_job_url = _is_linkedin_job(host, parsed.path) or _is_indeed_job(
        host, parsed.path, parsed.query
    )
    return "job_match" if is_job_url and has_full_jd else "summary_page"
