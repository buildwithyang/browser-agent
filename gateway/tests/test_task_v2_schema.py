import pytest
from app.modules.task import schema
from pydantic import TypeAdapter, ValidationError


def test_quick_insight_response_contains_only_insight_content() -> None:
    request = schema.QuickInsightRequest(url="https://example.com", title="Example")
    insight = schema.Insight(
        title="Page Summary",
        cards=[
            schema.TextInsightCard(
                id="summary",
                title="Summary",
                body_html="<p>Important page.</p>",
            )
        ],
    )

    response = schema.QuickInsightResponse(
        request=request,
        insight=insight,
        workspace=schema.WorkspaceDescriptor(resource_url="https://example.com/"),
    )

    assert response.insight.cards[0].type == "text"
    assert response.shortcuts == []
    assert response.workspace.model_dump() == {"resource_url": "https://example.com/"}
    assert "document" not in response.model_dump()


def test_prompt_shortcut_contract_includes_editable_prompt() -> None:
    shortcut = schema.PromptShortcut(
        id="tailor_resume",
        title="Tailor Resume",
        prompt="Plan the changes first.",
    )

    assert shortcut.model_dump() == {
        "id": "tailor_resume",
        "title": "Tailor Resume",
        "prompt": "Plan the changes first.",
    }


def test_chat_result_is_discriminated_and_markdown_only() -> None:
    """Model the Agent outcome without document HTML or section fields."""

    adapter = TypeAdapter(schema.ChatResult)
    reply = adapter.validate_python({"type": "reply", "markdown": "A focused answer."})
    draft = adapter.validate_python(
        {
            "type": "create_artifact",
            "markdown": "Generated CV.",
            "artifact_type": "cv",
            "title": "Tailored CV",
            "draft": "# Candidate",
        }
    )

    assert reply.type == "reply"
    assert draft.type == "create_artifact"
    with pytest.raises(ValidationError, match="html"):
        adapter.validate_python({"type": "reply", "markdown": "answer", "html": "<p>answer</p>"})
