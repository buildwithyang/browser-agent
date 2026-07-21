"""TaskService protocol-v3 Workspace stream and atomic reducer tests."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.agents.base import (
    AgentExecution,
    WorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.job_match import JobMatchAgent
from app.agents.stream import AgentCompleted, AgentDelta, AgentStatus
from app.modules.task.schema import (
    ActionId,
    AgentName,
    Artifact,
    Artifacts,
    ArtifactType,
    Attachment,
    ChatResult,
    CreateArtifactResult,
    HistoryMessage,
    QuickInsightActionWorkspaceRequest,
    ReplyResult,
    TaskRecordData,
    UpdateArtifactResult,
    UserMessageWorkspaceRequest,
    WorkspaceResultType,
)
from app.modules.task.service import TaskExecutionError, TaskService
from app.modules.task.stream_schema import WorkspaceStreamEvent


FIXED_NOW = datetime(2026, 7, 20, 12, 30, tzinfo=timezone.utc)
CV_PREVIEW_URL = "https://browser.buildwithyang.com"


class FakeWorkspaceAgent(WorkspaceAgent):
    """Return one prepared v2 execution while recording request-scoped context."""

    name = AgentName.SUMMARY_PAGE

    def __init__(
        self,
        result: ChatResult | object,
        *,
        error: Exception | None = None,
        requires_resume: bool = False,
    ) -> None:
        """Configure the result, optional failure, and resume dependency."""

        self.result = result
        self.error = error
        self.requires_resume = requires_resume
        self.calls: list[WorkspaceAgentContext] = []

    def handle_chat(self, ctx: WorkspaceAgentContext) -> AgentExecution[ChatResult]:
        """Record the v2 context and return or raise the prepared outcome."""

        self.calls.append(ctx)
        if self.error is not None:
            raise self.error
        return AgentExecution(
            content=self.result,  # type: ignore[arg-type]
            raw_result="raw specialist output",
            prompt="router and specialist prompt",
            model="specialist-model",
        )

    async def stream_chat(
        self,
        ctx: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStatus | AgentDelta | AgentCompleted]:
        """Stream the prepared reply with deterministic progress and terminal metadata."""

        self.calls.append(ctx)
        yield AgentStatus(stage="generating_reply")
        if self.error is not None:
            raise self.error
        if isinstance(self.result, ReplyResult):
            midpoint = max(1, len(self.result.markdown) // 2)
            for chunk in (self.result.markdown[:midpoint], self.result.markdown[midpoint:]):
                if chunk:
                    yield AgentDelta(text=chunk)
        yield AgentStatus(stage="finalizing")
        yield AgentCompleted(
            execution=AgentExecution(
                content=self.result,  # type: ignore[arg-type]
                raw_result="raw specialist output",
                prompt="router and specialist prompt",
                model="specialist-model",
            )
        )


class CleanupFailingWorkspaceAgent(FakeWorkspaceAgent):
    """Raise only while the service closes an otherwise complete Agent stream."""

    async def stream_chat(
        self,
        ctx: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStatus | AgentDelta | AgentCompleted]:
        """Yield one complete execution and then simulate cleanup failure."""

        try:
            async for event in super().stream_chat(ctx):
                yield event
        finally:
            raise RuntimeError("private provider cleanup detail")


class CloseTrackingWorkspaceAgent(FakeWorkspaceAgent):
    """Track cancellation cleanup for a partially consumed Agent stream."""

    def __init__(self, result: ChatResult) -> None:
        """Configure the result and an initially open stream marker."""

        super().__init__(result)
        self.stream_closed = False

    async def stream_chat(
        self,
        ctx: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStatus | AgentDelta | AgentCompleted]:
        """Mark the Agent iterator closed when its service consumer disconnects."""

        try:
            async for event in super().stream_chat(ctx):
                yield event
        finally:
            self.stream_closed = True


class InterruptedWorkspaceAgent(FakeWorkspaceAgent):
    """End after progress without yielding the required Agent terminal event."""

    async def stream_chat(
        self,
        ctx: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStatus | AgentDelta | AgentCompleted]:
        """Yield one status and then simulate an interrupted upstream stream."""

        self.calls.append(ctx)
        yield AgentStatus(stage="generating_reply")


class ArtifactDeltaWorkspaceAgent(FakeWorkspaceAgent):
    """Violate the Artifact status-only contract with one visible draft delta."""

    async def stream_chat(
        self,
        ctx: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStatus | AgentDelta | AgentCompleted]:
        """Emit an illegal Artifact draft before the terminal execution."""

        self.calls.append(ctx)
        yield AgentStatus(stage="generating_artifact", artifact_type=ArtifactType.CV)
        yield AgentDelta(text="# Private CV draft")
        yield AgentStatus(stage="finalizing")
        yield AgentCompleted(
            execution=AgentExecution(
                content=self.result,  # type: ignore[arg-type]
                raw_result="# Private CV draft",
                prompt="resume prompt",
                model="specialist-model",
            )
        )


class RecordingRepository:
    """Minimal operational-metrics Repository fake."""

    def __init__(self, *, used: int = 0) -> None:
        """Configure current rate-limit usage and an empty append log."""

        self.used = used
        self.records: list[TaskRecordData] = []

    def count_since(self, *, user_id: str, since: datetime) -> int:
        """Return the configured usage without storing Workspace state."""

        return self.used

    def append(self, record: TaskRecordData) -> None:
        """Record one metrics row for assertions."""

        self.records.append(record)


class FailingRepository(RecordingRepository):
    """Reject metrics writes with a deliberately private exception message."""

    def append(self, record: TaskRecordData) -> None:
        """Simulate a persistence error that must never enter application logs."""

        raise RuntimeError("PRIVATE resume and partial delta")


class ThreadRecordingRepository(RecordingRepository):
    """Record the worker thread used for stream terminal persistence."""

    def __init__(self) -> None:
        """Start without an observed append thread."""

        super().__init__()
        self.append_thread: int | None = None

    def append(self, record: TaskRecordData) -> None:
        """Capture the thread before storing the operational record."""

        self.append_thread = threading.get_ident()
        super().append(record)


class FakeResumeService:
    """Return one canonical resume and record the requested owner."""

    def __init__(self, text: str) -> None:
        """Store the canonical text returned per request."""

        self.text = text
        self.user_ids: list[str] = []

    def active_resume_text(self, *, user_id: str) -> str:
        """Return the configured active resume for the supplied user."""

        self.user_ids.append(user_id)
        return self.text


def _uuid_factory(*values: int) -> Callable[[], UUID]:
    """Build a deterministic UUID provider that fails on unexpected allocation."""

    iterator: Iterator[int] = iter(values)

    def next_uuid() -> UUID:
        """Return the next expected UUID."""

        try:
            return UUID(int=next(iterator))
        except StopIteration as exc:
            raise AssertionError("unexpected Workspace UUID allocation") from exc

    return next_uuid


def _service(
    agent: FakeWorkspaceAgent,
    *,
    uuid_values: tuple[int, ...] = (1, 2),
    repository: RecordingRepository | None = None,
    resume_service: FakeResumeService | None = None,
    perf_counter: Callable[[], float] | None = None,
    workspace_clock: Callable[[], datetime] | None = None,
) -> TaskService:
    """Build a TaskService with deterministic Workspace state providers."""

    return TaskService(
        agents={agent.name: agent},
        repository=repository,  # type: ignore[arg-type]
        resume_service=resume_service,  # type: ignore[arg-type]
        default_model="default-model",
        workspace_id_factory=_uuid_factory(*uuid_values),
        workspace_clock=workspace_clock or (lambda: FIXED_NOW),
        perf_counter=perf_counter,
    )


def _empty_artifacts() -> Artifacts:
    """Return the required empty fixed-key Artifact state."""

    return Artifacts(cv=None, cover_letter=None)


def _artifact_state(
    *artifact_types: ArtifactType,
) -> tuple[Artifacts, list[HistoryMessage]]:
    """Build valid latest Artifact snapshots plus immutable history Attachments."""

    artifacts: dict[ArtifactType, Artifact] = {}
    histories: list[HistoryMessage] = []
    for offset, artifact_type in enumerate(artifact_types, start=100):
        artifact_id = UUID(int=offset)
        title = "Existing CV" if artifact_type is ArtifactType.CV else "Existing Letter"
        draft = (
            "# Existing CV\n\nOpaque <cv>."
            if artifact_type is ArtifactType.CV
            else "# Existing Letter\n\nOpaque <letter>."
        )
        attachment = Attachment(
            id=UUID(int=offset + 10),
            artifact_id=artifact_id,
            version=1,
            type=artifact_type,
            title=title,
            content=CV_PREVIEW_URL if artifact_type is ArtifactType.CV else draft,
        )
        artifact = Artifact(
            id=artifact_id,
            type=artifact_type,
            version=1,
            title=title,
            draft=draft,
            attachment=attachment,
        )
        artifacts[artifact_type] = artifact
        histories.append(
            HistoryMessage(
                id=UUID(int=offset + 20),
                role="assistant",
                content=f"Created {title}.",
                action_id=ActionId.TAILOR_RESUME,
                created_at=FIXED_NOW,
                attachments=[attachment],
            )
        )
    return (
        Artifacts(
            cv=artifacts.get(ArtifactType.CV),
            cover_letter=artifacts.get(ArtifactType.COVER_LETTER),
        ),
        histories,
    )


def _user_request(
    *,
    histories: list[HistoryMessage] | None = None,
    artifacts: Artifacts | None = None,
    message: str = "Please help me.",
    url: str = "https://example.com/jobs/1",
    resource_url: str = "https://example.com/jobs/1",
) -> UserMessageWorkspaceRequest:
    """Build one valid user-message transition request."""

    return UserMessageWorkspaceRequest(
        trigger="user_message",
        url=url,
        resourceUrl=resource_url,
        operationId="00000000-0000-0000-0000-000000000001",
        actionId=ActionId.ASK_MORE,
        histories=histories or [],
        artifacts=artifacts or _empty_artifacts(),
        message=message,
    )


def _quick_request(
    *,
    histories: list[HistoryMessage] | None = None,
    artifacts: Artifacts | None = None,
) -> QuickInsightActionWorkspaceRequest:
    """Build one valid Quick Insight Action transition request."""

    return QuickInsightActionWorkspaceRequest(
        trigger="quick_insight_action",
        url="https://example.com/jobs/1",
        resourceUrl="https://example.com/jobs/1",
        operationId="00000000-0000-0000-0000-000000000001",
        actionId=ActionId.ANALYZE,
        histories=histories or [],
        artifacts=artifacts or _empty_artifacts(),
    )


def _reply(markdown: str = "## Reply\n\nOpaque <answer>.") -> ReplyResult:
    """Build one opaque Markdown reply result."""

    return ReplyResult(type=WorkspaceResultType.REPLY, markdown=markdown)


async def _collect_events(
    events: AsyncIterator[WorkspaceStreamEvent],
) -> list[WorkspaceStreamEvent]:
    """Collect one async service stream for synchronous pytest assertions."""

    return [event async for event in events]


def test_workspace_reply_stream_reduces_only_at_completed() -> None:
    """Map Agent progress and reduce the complete reply only at the terminal event."""

    repository = RecordingRepository()
    agent = FakeWorkspaceAgent(_reply("这个岗位很匹配"))
    service = _service(
        agent,
        uuid_values=(1, 2),
        repository=repository,
        perf_counter=iter((10.0, 10.25)).__next__,
    )

    prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
    events = asyncio.run(_collect_events(service.stream_workspace(prepared)))

    assert [event.type for event in events] == [
        "started",
        "status",
        "delta",
        "delta",
        "status",
        "completed",
    ]
    assert [event.sequence for event in events] == list(range(len(events)))
    assert all(event.operation_id == prepared.request.operation_id for event in events)
    terminal = events[-1]
    assert terminal.type == "completed"
    assert terminal.response.histories[-1].content == "这个岗位很匹配"
    assert terminal.response.meta.duration_ms == 250
    assert [record.status for record in repository.records] == ["completed"]


def test_workspace_stream_persists_outside_the_event_loop() -> None:
    """Offload synchronous terminal repository writes from the shared loop."""

    repository = ThreadRecordingRepository()
    service = _service(
        FakeWorkspaceAgent(_reply("complete")),
        uuid_values=(1, 2),
        repository=repository,
    )

    async def collect_on_loop() -> int:
        """Consume the stream and return the event-loop thread identity."""

        loop_thread = threading.get_ident()
        prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
        await _collect_events(service.stream_workspace(prepared))
        return loop_thread

    loop_thread = asyncio.run(collect_on_loop())

    assert repository.append_thread is not None
    assert repository.append_thread != loop_thread


def test_anonymous_job_match_cv_is_resolved_before_started(tmp_path) -> None:
    """Fail request preparation before streaming when the local CV is unavailable."""

    missing_cv = tmp_path / "missing.pdf"
    agent = JobMatchAgent(cv_path=missing_cv, model="fake-model")
    service = TaskService(
        agents={AgentName.JOB_MATCH: agent},
        repository=None,
        resume_service=None,
        default_model="fake-model",
    )
    url = "https://ae.indeed.com/viewjob?jk=5b927211cdf9ea42"
    request = _user_request(url=url, resource_url=url).model_copy(
        update={"selected_text": "complete job description " * 60}
    )

    with pytest.raises(FileNotFoundError, match="missing.pdf"):
        service.prepare_workspace_stream(request, user_id=None)


def test_workspace_stream_failure_never_reduces_or_emits_completed() -> None:
    """Convert a post-start Agent failure into one bounded failed terminal event."""

    repository = RecordingRepository()
    request = _user_request()
    before = request.model_dump_json()
    service = _service(
        FakeWorkspaceAgent(_reply(), error=RuntimeError("provider unavailable")),
        uuid_values=(),
        repository=repository,
        perf_counter=iter((10.0, 10.1)).__next__,
    )

    prepared = service.prepare_workspace_stream(request, user_id="user-1")
    events = asyncio.run(_collect_events(service.stream_workspace(prepared)))

    assert [event.type for event in events] == ["started", "status", "failed"]
    assert events[-1].type == "failed"
    assert events[-1].code == "model_error"
    assert "provider unavailable" not in events[-1].message
    assert not any(event.type == "completed" for event in events)
    assert request.model_dump_json() == before
    assert [record.status for record in repository.records] == ["failed"]


def test_workspace_stream_requires_one_agent_completed_event() -> None:
    """Emit stream_interrupted when the Agent iterator ends without a result."""

    repository = RecordingRepository()
    service = _service(
        InterruptedWorkspaceAgent(_reply()),
        uuid_values=(),
        repository=repository,
    )

    prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
    events = asyncio.run(_collect_events(service.stream_workspace(prepared)))

    assert [event.type for event in events] == ["started", "status", "failed"]
    assert events[-1].type == "failed"
    assert events[-1].code == "stream_interrupted"
    assert [record.status for record in repository.records] == ["failed"]


def test_workspace_stream_rejects_invalid_completed_model_output() -> None:
    """Fail atomically when the terminal Agent execution bypassed model validation."""

    repository = RecordingRepository()
    invalid_result = ReplyResult.model_construct(
        type=WorkspaceResultType.REPLY,
        markdown="x" * 100_001,
    )
    service = _service(
        FakeWorkspaceAgent(invalid_result),
        uuid_values=(),
        repository=repository,
    )

    prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
    events = asyncio.run(_collect_events(service.stream_workspace(prepared)))

    assert events[-1].type == "failed"
    assert events[-1].code == "invalid_model_output"
    assert not any(event.type == "completed" for event in events)
    assert [record.status for record in repository.records] == ["failed"]


def test_workspace_stream_maps_gateway_reducer_failure_to_internal_error() -> None:
    """Keep Gateway-owned final state failures distinct from invalid model output."""

    repository = RecordingRepository()
    service = _service(
        FakeWorkspaceAgent(_reply()),
        uuid_values=(1, 1),
        repository=repository,
    )

    prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
    events = asyncio.run(_collect_events(service.stream_workspace(prepared)))

    assert events[-1].type == "failed"
    assert events[-1].code == "internal_error"
    assert not any(event.type == "completed" for event in events)
    assert [record.status for record in repository.records] == ["failed"]


def test_workspace_stream_cleanup_failure_cannot_follow_completed_terminal() -> None:
    """Ignore cleanup exceptions after one canonical completed event is committed."""

    repository = RecordingRepository()
    service = _service(
        CleanupFailingWorkspaceAgent(_reply("complete")),
        uuid_values=(1, 2),
        repository=repository,
    )

    prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
    events = asyncio.run(_collect_events(service.stream_workspace(prepared)))

    terminals = [event for event in events if event.type in {"completed", "failed"}]
    assert [event.type for event in terminals] == ["completed"]
    assert [record.status for record in repository.records] == ["completed"]


def test_workspace_stream_disconnect_closes_agent_without_partial_persistence() -> None:
    """Close the active Agent stream and store only bounded failure metrics."""

    repository = RecordingRepository()
    agent = CloseTrackingWorkspaceAgent(_reply("partial reply"))
    service = _service(agent, uuid_values=(), repository=repository)
    request = _user_request().model_copy(
        update={
            "title": "Private title",
            "page_text": "Private page body",
            "selected_text": "Private selection",
        }
    )
    before = request.model_dump_json()

    async def disconnect() -> None:
        """Consume progress and then close the service stream like the API body."""

        prepared = service.prepare_workspace_stream(request, user_id="user-1")
        events = service.stream_workspace(prepared)
        assert (await anext(events)).type == "started"
        assert (await anext(events)).type == "status"
        await events.aclose()

    asyncio.run(disconnect())

    assert agent.stream_closed is True
    assert request.model_dump_json() == before
    assert [record.status for record in repository.records] == ["failed"]
    record = repository.records[0]
    assert (record.url, record.title, record.prompt, record.page_text, record.result) == (
        None,
        None,
        None,
        None,
        None,
    )


def test_workspace_stream_close_after_started_records_one_interruption() -> None:
    """Own the lifecycle at started without opening the lazy Agent iterator."""

    repository = RecordingRepository()
    agent = CloseTrackingWorkspaceAgent(_reply("unused reply"))
    service = _service(agent, uuid_values=(), repository=repository)

    async def disconnect_after_started() -> None:
        """Close immediately after the first wire event is observed."""

        prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
        events = service.stream_workspace(prepared)
        assert (await anext(events)).type == "started"
        await events.aclose()

    asyncio.run(disconnect_after_started())

    assert agent.calls == []
    assert agent.stream_closed is False
    assert [record.status for record in repository.records] == ["failed"]
    assert [record.error for record in repository.records] == ["stream_interrupted"]


def test_workspace_stream_failure_does_not_log_private_repository_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep raw persistence failures out of the streamed failure log path."""

    service = _service(
        FakeWorkspaceAgent(_reply(), error=RuntimeError("provider unavailable")),
        uuid_values=(),
        repository=FailingRepository(),
    )

    prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
    events = asyncio.run(_collect_events(service.stream_workspace(prepared)))

    assert events[-1].type == "failed"
    assert "PRIVATE resume and partial delta" not in caplog.text


def _create(artifact_type: ArtifactType) -> CreateArtifactResult:
    """Build one complete opaque create result."""

    draft = (
        "# Tailored CV\n\n<script>opaque cv</script>"
        if artifact_type is ArtifactType.CV
        else "# Cover Letter\n\n<script>opaque letter</script>"
    )
    return CreateArtifactResult(
        type=WorkspaceResultType.CREATE_ARTIFACT,
        markdown="Created the complete draft.",
        artifact_type=artifact_type,
        title="Tailored CV" if artifact_type is ArtifactType.CV else "Cover Letter",
        draft=draft,
    )


def test_workspace_stream_rejects_artifact_deltas_before_exposing_them() -> None:
    """Enforce the Artifact status-only lifecycle at the Gateway boundary."""

    repository = RecordingRepository()
    service = _service(
        ArtifactDeltaWorkspaceAgent(_create(ArtifactType.CV)),
        uuid_values=(),
        repository=repository,
    )

    prepared = service.prepare_workspace_stream(_user_request(), user_id="user-1")
    events = asyncio.run(_collect_events(service.stream_workspace(prepared)))

    assert [event.type for event in events] == ["started", "status", "failed"]
    assert events[-1].type == "failed"
    assert events[-1].code == "invalid_model_output"
    assert [record.error for record in repository.records] == ["invalid_model_output"]


def _update(artifact_type: ArtifactType) -> UpdateArtifactResult:
    """Build one complete opaque update result."""

    return UpdateArtifactResult(
        type=WorkspaceResultType.UPDATE_ARTIFACT,
        markdown="Updated the complete draft.",
        artifact_type=artifact_type,
        title="Updated CV" if artifact_type is ArtifactType.CV else "Updated Letter",
        draft="# Updated\n\n<style>opaque snapshot</style>",
    )


def test_user_message_appends_user_then_assistant_with_gateway_identity() -> None:
    """Append exactly two server-owned messages for a user-message trigger."""

    agent = FakeWorkspaceAgent(_reply())
    response = _service(agent, uuid_values=(1, 2)).workspace(
        _user_request(message="What matters most?"),
        user_id=None,
    )

    assert [(message.role, message.content) for message in response.histories] == [
        ("user", "What matters most?"),
        ("assistant", "## Reply\n\nOpaque <answer>."),
    ]
    assert [message.id for message in response.histories] == [UUID(int=1), UUID(int=2)]
    assert all(message.created_at == FIXED_NOW for message in response.histories)
    assert all(message.attachments == [] for message in response.histories)


def test_quick_action_appends_only_one_assistant_message() -> None:
    """Do not synthesize a User message for a deterministic Quick Action."""

    response = _service(
        FakeWorkspaceAgent(_reply("Quick analysis.")),
        uuid_values=(1,),
    ).workspace(_quick_request(), user_id=None)

    assert [(message.role, message.content) for message in response.histories] == [
        ("assistant", "Quick analysis.")
    ]
    assert response.histories[0].id == UUID(int=1)


def test_reply_returns_both_artifacts_byte_for_byte_unchanged() -> None:
    """Treat a reply as a history-only transition with opaque Artifact state."""

    artifacts, histories = _artifact_state(ArtifactType.CV, ArtifactType.COVER_LETTER)
    before = artifacts.model_dump_json()

    response = _service(FakeWorkspaceAgent(_reply()), uuid_values=(1, 2)).workspace(
        _user_request(histories=histories, artifacts=artifacts),
        user_id=None,
    )

    assert response.artifacts.model_dump_json() == before


@pytest.mark.parametrize("artifact_type", [ArtifactType.CV, ArtifactType.COVER_LETTER])
def test_create_allocates_version_one_artifact_and_one_attachment(
    artifact_type: ArtifactType,
) -> None:
    """Create a complete first snapshot only after a successful Agent result."""

    response = _service(
        FakeWorkspaceAgent(_create(artifact_type)),
        uuid_values=(1, 2, 3, 4),
    ).workspace(_user_request(), user_id=None)
    artifact = (
        response.artifacts.cv
        if artifact_type is ArtifactType.CV
        else response.artifacts.cover_letter
    )

    assert artifact is not None
    assert artifact.id == UUID(int=2)
    assert artifact.version == 1
    assert artifact.attachment.id == UUID(int=3)
    assert artifact.attachment.artifact_id == artifact.id
    assert response.histories[-1].id == UUID(int=4)
    assert response.histories[-1].created_at == FIXED_NOW
    assert response.histories[-1].attachments == [artifact.attachment]


def test_update_reuses_artifact_id_and_appends_immutable_attachment() -> None:
    """Advance one same-type version without changing its historical Attachment."""

    artifacts, histories = _artifact_state(ArtifactType.COVER_LETTER)
    previous = artifacts.cover_letter
    assert previous is not None
    previous_attachment_json = histories[-1].attachments[0].model_dump_json()

    response = _service(
        FakeWorkspaceAgent(_update(ArtifactType.COVER_LETTER)),
        uuid_values=(1, 2, 3),
    ).workspace(
        _user_request(histories=histories, artifacts=artifacts),
        user_id=None,
    )
    updated = response.artifacts.cover_letter

    assert updated is not None
    assert updated.id == previous.id
    assert updated.version == previous.version + 1
    assert updated.attachment.id == UUID(int=2)
    assert response.histories[-1].attachments == [updated.attachment]
    assert response.histories[0].attachments[0].model_dump_json() == previous_attachment_json


def test_updating_cover_letter_preserves_coexisting_cv() -> None:
    """Replace only the addressed fixed-key Artifact slot."""

    artifacts, histories = _artifact_state(ArtifactType.CV, ArtifactType.COVER_LETTER)
    cv_before = artifacts.cv.model_dump_json() if artifacts.cv is not None else None

    response = _service(
        FakeWorkspaceAgent(_update(ArtifactType.COVER_LETTER)),
        uuid_values=(1, 2, 3),
    ).workspace(
        _user_request(histories=histories, artifacts=artifacts),
        user_id=None,
    )

    assert response.artifacts.cv is not None
    assert response.artifacts.cover_letter is not None
    assert response.artifacts.cv.model_dump_json() == cv_before


def test_attachment_content_is_gateway_owned_and_draft_remains_opaque() -> None:
    """Store full Cover Letter Markdown but expose CV through the fixed preview URL."""

    cover_result = _create(ArtifactType.COVER_LETTER)
    cover = _service(
        FakeWorkspaceAgent(cover_result),
        uuid_values=(1, 2, 3),
    ).workspace(_quick_request(), user_id=None).artifacts.cover_letter
    cv_result = _create(ArtifactType.CV)
    cv = _service(
        FakeWorkspaceAgent(cv_result),
        uuid_values=(4, 5, 6),
    ).workspace(_quick_request(), user_id=None).artifacts.cv

    assert cover is not None and cover.attachment.content == cover_result.draft
    assert cover.draft == "# Cover Letter\n\n<script>opaque letter</script>"
    assert cv is not None and cv.attachment.content == CV_PREVIEW_URL
    assert cv.draft == "# Tailored CV\n\n<script>opaque cv</script>"


@pytest.mark.parametrize(
    "agent",
    [
        FakeWorkspaceAgent(object()),
        FakeWorkspaceAgent(_reply(), error=RuntimeError("model unavailable")),
    ],
)
def test_agent_failures_allocate_no_workspace_state(agent: FakeWorkspaceAgent) -> None:
    """Reject invalid/model failures before allocating any next-state identity."""

    request = _user_request()
    before = request.model_dump_json()
    service = _service(agent, uuid_values=())

    with pytest.raises(TaskExecutionError):
        service.workspace(request, user_id=None)

    assert request.model_dump_json() == before


def test_invalid_cover_letter_snapshot_fails_before_metrics_or_state_allocation() -> None:
    """Validate nested Attachment constraints inside the Agent failure boundary."""

    repository = RecordingRepository()
    clock_calls = 0

    def workspace_clock() -> datetime:
        """Record an invalid early attempt to allocate transition time."""

        nonlocal clock_calls
        clock_calls += 1
        return FIXED_NOW

    invalid_result = CreateArtifactResult(
        type=WorkspaceResultType.CREATE_ARTIFACT,
        markdown="Created it.",
        artifact_type=ArtifactType.COVER_LETTER,
        title="Cover Letter",
        draft="",
    )
    service = _service(
        FakeWorkspaceAgent(invalid_result),
        uuid_values=(),
        repository=repository,
        workspace_clock=workspace_clock,
    )

    with pytest.raises(TaskExecutionError, match="Attachment"):
        service.workspace(_user_request(), user_id="user-1")

    assert clock_calls == 0
    assert len(repository.records) == 1
    assert repository.records[0].status == "failed"


def test_unvalidated_chat_result_fails_before_workspace_state_allocation() -> None:
    """Fully revalidate a model-constructed ChatResult before clock or UUID use."""

    repository = RecordingRepository()
    clock_calls = 0

    def workspace_clock() -> datetime:
        """Record any forbidden state-time allocation."""

        nonlocal clock_calls
        clock_calls += 1
        return FIXED_NOW

    invalid_result = ReplyResult.model_construct(
        type=WorkspaceResultType.REPLY,
        markdown="x" * 100_001,
    )
    service = _service(
        FakeWorkspaceAgent(invalid_result),
        uuid_values=(),
        repository=repository,
        workspace_clock=workspace_clock,
    )

    with pytest.raises(TaskExecutionError):
        service.workspace(_user_request(), user_id="user-1")

    assert clock_calls == 0
    assert [record.status for record in repository.records] == ["failed"]


def test_workspace_clock_failure_records_only_failed_metrics() -> None:
    """Commit no completed metric when next-state time allocation fails."""

    repository = RecordingRepository()

    def failing_clock() -> datetime:
        """Simulate a Gateway-owned next-state provider failure."""

        raise RuntimeError("workspace clock unavailable")

    service = _service(
        FakeWorkspaceAgent(_reply()),
        uuid_values=(),
        repository=repository,
        workspace_clock=failing_clock,
    )

    with pytest.raises(TaskExecutionError, match="workspace clock unavailable"):
        service.workspace(_user_request(), user_id="user-1")

    assert [record.status for record in repository.records] == ["failed"]


def test_final_response_validation_failure_records_only_failed_metrics() -> None:
    """Treat invalid provider identity as a failed atomic Workspace operation."""

    repository = RecordingRepository()
    service = _service(
        FakeWorkspaceAgent(_reply()),
        uuid_values=(1, 1),
        repository=repository,
    )

    with pytest.raises(TaskExecutionError, match="message IDs"):
        service.workspace(_user_request(), user_id="user-1")

    assert [record.status for record in repository.records] == ["failed"]


def test_resume_injection_metrics_url_normalization_and_full_duration() -> None:
    """Preserve operational orchestration around the complete v2 Agent call."""

    perf_values = iter((10.0, 10.375))
    repository = RecordingRepository()
    resume_service = FakeResumeService("# Canonical Resume")
    agent = FakeWorkspaceAgent(_reply(), requires_resume=True)
    service = _service(
        agent,
        uuid_values=(1, 2),
        repository=repository,
        resume_service=resume_service,
        perf_counter=lambda: next(perf_values),
    )
    request = _user_request(
        url="https://Example.com/jobs/1?utm_source=mail&b=2&a=1#top",
        resource_url="https://example.com/jobs/1?a=1&b=2",
    )

    response = service.workspace(request, user_id="user-1")

    assert response.resource_url == "https://example.com/jobs/1?a=1&b=2"
    assert agent.calls[0].resume_text == "# Canonical Resume"
    assert resume_service.user_ids == ["user-1"]
    assert response.meta.model == "specialist-model"
    assert response.meta.duration_ms == 375
    assert len(repository.records) == 1
    assert repository.records[0].status == "completed"
    assert repository.records[0].duration_ms == 375
    assert repository.records[0].result_chars == len("raw specialist output")


def test_message_capacity_allows_last_user_and_quick_transitions() -> None:
    """Permit legal terminal transitions that return eleven total messages."""

    nine = [HistoryMessage(role="user", content=str(index)) for index in range(9)]
    user_response = _service(
        FakeWorkspaceAgent(_reply()),
        uuid_values=(1, 2),
    ).workspace(_user_request(histories=nine), user_id=None)
    ten = [HistoryMessage(role="user", content=str(index)) for index in range(10)]
    quick_response = _service(
        FakeWorkspaceAgent(_reply()),
        uuid_values=(3,),
    ).workspace(_quick_request(histories=ten), user_id=None)

    assert len(user_response.histories) == 11
    assert len(quick_response.histories) == 11
    with pytest.raises(ValidationError, match="histories"):
        _user_request(histories=ten)
