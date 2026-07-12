from app.agents.job_match import MIN_JOB_CONTENT_CHARS
from app.modules.task.router import route_browser_task
from app.modules.task.schema import TaskCreate


LONG_JD = "Responsibilities and requirements for this engineering role. " * 30
assert len(LONG_JD) >= MIN_JOB_CONTENT_CHARS


def task(url: str, selected: str = LONG_JD) -> TaskCreate:
    return TaskCreate(url=url, selectedText=selected, agent="browser_agent")


def test_linkedin_job_with_full_selection_routes_to_job_match():
    assert route_browser_task(task("https://www.linkedin.com/jobs/view/123")) == "job_match"


def test_indeed_job_with_full_selection_routes_to_job_match():
    assert route_browser_task(task("https://ae.indeed.com/viewjob?jk=abc")) == "job_match"


def test_linkedin_profile_falls_back_to_summary():
    assert route_browser_task(task("https://www.linkedin.com/in/someone")) == "summary_page"


def test_job_url_with_short_selection_falls_back_to_summary():
    assert (
        route_browser_task(
            task("https://www.linkedin.com/jobs/view/123", "short")
        )
        == "summary_page"
    )


def test_unknown_site_falls_back_to_summary():
    assert route_browser_task(task("https://example.com/jobs/123")) == "summary_page"
