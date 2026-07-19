from __future__ import annotations

import html
import re

from app.modules.task.legacy.schema import (
    LegacyAction,
    LegacyJobOverview,
    LegacyQuickInsight,
    LegacySection,
    LegacyTaskRequest,
    LegacyTaskResponse,
)
from app.modules.task.schema import (
    AgentName,
    DetailsInsightCard,
    QuickInsightRequest,
    QuickInsightResponse,
    ScoreInsightCard,
    TaskRequest,
    TaskResponse,
    TextInsightCard,
)
from app.modules.task.router import route_browser_task

_TAG_RE = re.compile(r"<[^>]+>")


def to_quick_request(request: LegacyTaskRequest) -> QuickInsightRequest:
    """Translate legacy page fields into the public Quick Insight contract."""

    payload = request.model_dump(
        by_alias=True,
        exclude={"agent", "sections", "prior_result"},
    )
    return QuickInsightRequest.model_validate(payload)


def to_task_request(request: LegacyTaskRequest) -> TaskRequest:
    """Translate a legacy document request into the internal task input."""

    if request.sections and "cover_letter" in request.sections:
        action_id = "write_cover_letter"
    elif request.agent is AgentName.JOB_MATCH:
        action_id = "deep_analysis"
    else:
        action_id = "summary"
    payload = request.model_dump(
        by_alias=True,
        exclude={"agent", "sections", "prior_result"},
    )
    payload.update({"actionId": action_id, "priorResult": request.prior_result})
    return TaskRequest.model_validate(payload)


def is_quick_request(request: LegacyTaskRequest) -> bool:
    """Return whether the old transport expects the Quick Insight flow."""

    return request.agent is AgentName.BROWSER_AGENT or request.intent == "quick_insight"


def from_quick_response(
    response: QuickInsightResponse,
    *,
    legacy_request: LegacyTaskRequest,
) -> LegacyTaskResponse:
    """Adapt Quick Insight output back to the deployed legacy wire shape."""

    score = next(
        (card for card in response.insight.cards if isinstance(card, ScoreInsightCard)),
        None,
    )
    overview = next(
        (card for card in response.insight.cards if isinstance(card, DetailsInsightCard)),
        None,
    )
    text_cards = {
        card.id: card
        for card in response.insight.cards
        if isinstance(card, TextInsightCard)
    }
    summary_card = text_cards.get("summary")
    summary_html = summary_card.body_html if summary_card else ""
    result = html.unescape(_TAG_RE.sub("", summary_html)).strip()
    items = {item.label: item.value for item in overview.items} if overview else {}
    legacy_insight = LegacyQuickInsight(
        type="job_match" if score else "summary",
        title=response.insight.title,
        summary_html=summary_html,
        score=score.score if score else None,
        recommendation=score.recommendation if score else None,
        reason=score.reason if score else "",
        job_overview=(
            LegacyJobOverview(
                industry_business=items.get("industry_business", ""),
                role_focus=items.get("role_focus", ""),
                summary=overview.summary,
            )
            if overview
            else None
        ),
        top_strength=html.unescape(
            _TAG_RE.sub("", text_cards.get("top_strength").body_html)
        ).strip()
        if text_cards.get("top_strength")
        else "",
        top_gap=html.unescape(
            _TAG_RE.sub("", text_cards.get("top_gap").body_html)
        ).strip()
        if text_cards.get("top_gap")
        else "",
    )
    routed_agent = (
        route_browser_task(response.request)
        if legacy_request.agent is AgentName.BROWSER_AGENT
        else legacy_request.agent
    )
    response_request = response.request.model_dump(by_alias=True)
    response_request["agent"] = routed_agent
    return LegacyTaskResponse(
        id=response.meta.id,
        created_at=response.meta.created_at,
        status=response.meta.status,
        request=LegacyTaskRequest.model_validate(response_request),
        input_chars=response.meta.input_chars,
        model=response.meta.model,
        result=result,
        result_html=summary_html,
        actions=[
            LegacyAction(id=action.id, label=action.title, task_type=action.id)
            for action in response.actions
        ],
        insight=legacy_insight,
        started_at=response.meta.started_at,
        finished_at=response.meta.finished_at,
        duration_ms=response.meta.duration_ms,
    )


def from_task_response(
    response: TaskResponse,
    *,
    legacy_request: LegacyTaskRequest,
) -> LegacyTaskResponse:
    """Adapt legacy document execution back to the deployed wire shape."""

    response_request = response.request.model_dump(by_alias=True)
    response_request["agent"] = legacy_request.agent
    return LegacyTaskResponse(
        id=response.meta.id,
        created_at=response.meta.created_at,
        status=response.meta.status,
        request=LegacyTaskRequest.model_validate(response_request),
        input_chars=response.meta.input_chars,
        model=response.meta.model,
        result=response.document.text,
        result_html=response.document.html,
        sections=[LegacySection.model_validate(section.model_dump()) for section in response.document.sections],
        started_at=response.meta.started_at,
        finished_at=response.meta.finished_at,
        duration_ms=response.meta.duration_ms,
    )
