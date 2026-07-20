from app.agents.job_match import MIN_JOB_CONTENT_CHARS
from app.modules.task.router import route_browser_task
from app.modules.task.schema import AgentName, QuickInsightRequest


LONG_JD = "Responsibilities and requirements for this engineering role. " * 30
assert len(LONG_JD) >= MIN_JOB_CONTENT_CHARS


def task(url: str, selected: str = LONG_JD) -> QuickInsightRequest:
    """Build one browser routing request with configurable selected text."""

    return QuickInsightRequest(url=url, selectedText=selected)


def test_linkedin_job_with_full_selection_routes_to_job_match():
    """Route a complete LinkedIn job page to the job Agent."""

    assert (
        route_browser_task(task("https://www.linkedin.com/jobs/view/123"))
        is AgentName.JOB_MATCH
    )


def test_router_returns_agent_name_enum():
    """Return the typed internal Agent identifier from the router."""

    assert (
        route_browser_task(task("https://www.linkedin.com/jobs"))
        is AgentName.JOB_MATCH
    )


def test_indeed_job_with_full_selection_routes_to_job_match():
    """Route a complete Indeed job page to the job Agent."""

    assert (
        route_browser_task(task("https://ae.indeed.com/viewjob?jk=abc"))
        is AgentName.JOB_MATCH
    )


def test_linkedin_profile_with_full_selection_routes_to_job_match():
    """Use the selected JD evidence on any LinkedIn page."""

    assert (
        route_browser_task(task("https://www.linkedin.com/in/someone"))
        is AgentName.JOB_MATCH
    )


def test_linkedin_search_results_with_current_job_routes_to_job_match():
    """Recognize the active job embedded in LinkedIn search results."""

    assert (
        route_browser_task(
            task(
                "https://www.linkedin.com/jobs/search-results/"
                "?currentJobId=4439779617"
            )
        )
        is AgentName.JOB_MATCH
    )


def test_linkedin_collections_with_full_selection_routes_to_job_match():
    """Use complete selected evidence on LinkedIn collections pages."""

    assert (
        route_browser_task(task("https://www.linkedin.com/jobs/collections"))
        is AgentName.JOB_MATCH
    )


def test_indeed_page_with_full_selection_routes_to_job_match():
    """Use complete selected evidence on any Indeed page."""

    assert (
        route_browser_task(task("https://ae.indeed.com/jobs?notjk=value"))
        is AgentName.JOB_MATCH
    )


def test_job_url_with_short_selection_falls_back_to_summary():
    """Reject a LinkedIn job route when selected evidence is sparse."""

    assert (
        route_browser_task(
            task("https://www.linkedin.com/jobs/view/123", "short")
        )
        is AgentName.SUMMARY_PAGE
    )


def test_indeed_page_with_short_selection_falls_back_to_summary():
    """Reject an Indeed job route when selected evidence is sparse."""

    assert (
        route_browser_task(task("https://ae.indeed.com/jobs", "short"))
        is AgentName.SUMMARY_PAGE
    )


def test_unknown_site_falls_back_to_summary():
    """Keep unknown hosts on the generic summary Agent."""

    assert (
        route_browser_task(task("https://example.com/jobs/123"))
        is AgentName.SUMMARY_PAGE
    )
