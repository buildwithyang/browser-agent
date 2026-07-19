from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.agents.job_match import MIN_JOB_CONTENT_CHARS
from app.modules.task.schema import AgentName, PageContext

_LINKEDIN_JOB_PATH_RE = re.compile(r"^/jobs/view/([^/]+)")


def _is_linkedin_host(host: str) -> bool:
    """Return whether a host belongs to LinkedIn."""

    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _is_indeed_host(host: str) -> bool:
    """Return whether a host belongs to an Indeed regional subdomain."""

    return host == "indeed.com" or host.endswith(".indeed.com")


def _query_value(query: list[tuple[str, str]], key: str) -> str | None:
    """Return the first non-empty value for an exact query key."""

    return next((value for name, value in query if name == key and value), None)


def normalize_resource_url(url: str) -> str:
    """Normalize a browser URL into a stable Workspace resource identity."""

    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("url must be an absolute HTTP(S) URL")

    query = parse_qsl(parsed.query, keep_blank_values=True)
    if _is_linkedin_host(host):
        path_match = _LINKEDIN_JOB_PATH_RE.match(parsed.path)
        job_id = path_match.group(1) if path_match else _query_value(query, "currentJobId")
        if job_id:
            return f"https://www.linkedin.com/jobs/view/{job_id}"

    if _is_indeed_host(host):
        job_id = _query_value(query, "jk") or _query_value(query, "vjk")
        if job_id:
            return f"https://{host}/viewjob?{urlencode([('jk', job_id)])}"

    filtered_query = sorted(
        (name, value)
        for name, value in query
        if not name.lower().startswith("utm_")
    )
    # urlsplit removes IPv6 brackets from hostname; URL authority requires them.
    netloc = f"[{host}]" if ":" in host else host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit(
        (scheme, netloc, parsed.path or "/", urlencode(filtered_query), "")
    )


def route_browser_task(task: PageContext) -> AgentName:
    """Route current page context to the stateless internal Agent."""

    parsed = urlsplit(task.url)
    host = (parsed.hostname or "").lower()
    has_full_jd = len(task.selected_text.strip()) >= MIN_JOB_CONTENT_CHARS
    is_supported_host = _is_linkedin_host(host) or _is_indeed_host(host)
    return (
        AgentName.JOB_MATCH
        if is_supported_host and has_full_jd
        else AgentName.SUMMARY_PAGE
    )
