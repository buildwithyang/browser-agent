from app.agents.job_match import MIN_JOB_CONTENT_CHARS
from app.modules.task.router import route_browser_task
from app.modules.task.schema import AgentName, TaskCreate


LONG_JD = "Responsibilities and requirements for this engineering role. " * 30
assert len(LONG_JD) >= MIN_JOB_CONTENT_CHARS


def task(url: str, selected: str = LONG_JD) -> TaskCreate:
    return TaskCreate(url=url, selectedText=selected, agent=AgentName.BROWSER_AGENT)


def test_linkedin_job_with_full_selection_routes_to_job_match():
    assert (
        route_browser_task(task("https://www.linkedin.com/jobs/view/123"))
        is AgentName.JOB_MATCH
    )


def test_router_returns_agent_name_enum():
    assert (
        route_browser_task(task("https://www.linkedin.com/jobs"))
        is AgentName.JOB_MATCH
    )


def test_indeed_job_with_full_selection_routes_to_job_match():
    assert (
        route_browser_task(task("https://ae.indeed.com/viewjob?jk=abc"))
        is AgentName.JOB_MATCH
    )


def test_linkedin_profile_with_full_selection_routes_to_job_match():
    assert (
        route_browser_task(task("https://www.linkedin.com/in/someone"))
        is AgentName.JOB_MATCH
    )


def test_linkedin_search_results_with_current_job_routes_to_job_match():
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
    assert (
        route_browser_task(task("https://www.linkedin.com/jobs/collections"))
        is AgentName.JOB_MATCH
    )


def test_indeed_page_with_full_selection_routes_to_job_match():
    assert (
        route_browser_task(task("https://ae.indeed.com/jobs?notjk=value"))
        is AgentName.JOB_MATCH
    )


def test_job_url_with_short_selection_falls_back_to_summary():
    assert (
        route_browser_task(
            task("https://www.linkedin.com/jobs/view/123", "short")
        )
        is AgentName.SUMMARY_PAGE
    )


def test_indeed_page_with_short_selection_falls_back_to_summary():
    assert (
        route_browser_task(task("https://ae.indeed.com/jobs", "short"))
        is AgentName.SUMMARY_PAGE
    )


def test_unknown_site_falls_back_to_summary():
    assert (
        route_browser_task(task("https://example.com/jobs/123"))
        is AgentName.SUMMARY_PAGE
    )
