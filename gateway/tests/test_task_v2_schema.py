from app.modules.task import schema


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

    response = schema.QuickInsightResponse(request=request, insight=insight)

    assert response.insight.cards[0].type == "text"
    assert response.actions == []
    assert "document" not in response.model_dump()


def test_task_response_contains_document_not_insight() -> None:
    request = schema.TaskRequest(
        url="https://example.com/jobs/1",
        actionId="deep_analysis",
    )
    document = schema.DocumentContent(
        text="Analysis",
        html="<p>Analysis</p>",
        sections=[schema.Section(id="analysis", title="Analysis", html="<p>Analysis</p>")],
    )

    response = schema.TaskResponse(request=request, document=document)

    assert response.request.action_id == "deep_analysis"
    assert response.document.sections[0].id == "analysis"
    assert "insight" not in response.model_dump()


def test_new_action_contract_uses_title_only() -> None:
    action = schema.Action(id="tailor_resume", title="Tailor Resume")

    assert action.model_dump() == {"id": "tailor_resume", "title": "Tailor Resume"}
