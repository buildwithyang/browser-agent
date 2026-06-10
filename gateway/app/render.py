import markdown
import nh3


def render_markdown(text: str) -> str:
    """Convert Markdown to sanitized HTML that is safe to inject into a page.

    The model output is rendered to HTML with the common Markdown subset
    (headings, lists, fenced code, tables) and then run through nh3 (an
    ammonia-based sanitizer) which strips scripts, event handlers, and unsafe
    URL schemes — so the extension can drop it straight into a Shadow DOM.
    """
    html = markdown.markdown(
        text or "",
        # nl2br keeps single-newline lines (common in LLM output) on separate
        # lines instead of collapsing them into one.
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
    )
    return nh3.clean(html)
