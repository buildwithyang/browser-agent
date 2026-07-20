# Workspace Streaming Design

**Date:** 2026-07-20  
**Status:** Approved in conversation; awaiting written-spec review  
**Scope:** Gateway Workspace execution, Extension Background transport, and Side Panel transient UI

## 1. Goal

Workspace currently waits for the model, structured-result parsing, state reduction, and the
complete JSON response before displaying any new content. During a long model call, the Side
Panel therefore looks stalled.

This change makes normal Assistant Markdown visibly stream while preserving the existing
Workspace invariant: only one fully validated `histories + artifacts` state may be persisted.

The intended user experience is:

1. A submitted User Message appears immediately and the composer clears.
2. The Assistant shows the current stage.
3. Normal replies render incrementally as Markdown.
4. CV and Cover Letter generation show status only.
5. A complete Gateway response atomically replaces all transient UI.
6. A failed stream never changes canonical Workspace state and restores the submitted text.

## 2. Non-goals

- Streaming CV or Cover Letter draft tokens.
- Server-side Workspace threads, cross-device synchronization, or Artifact persistence.
- SSE, WebSocket, polling, or the OpenAI Responses API.
- A user-facing stop-generation button in the first release.
- Changing the local Workspace storage schema or the ten-input-message limit.
- Refactoring Quick Insight into an asynchronous or streaming path.

## 3. Chosen approach

Use three independent streaming boundaries:

```text
AsyncOpenAI Chat Completions
        ↓ AsyncIterator[str]
FastAPI / Starlette StreamingResponse
        ↓ application/x-ndjson
Extension Background fetch ReadableStream
        ↓ cumulative chrome.runtime messages
Side Panel transient turn
```

The model boundary uses only OpenAI-compatible Chat Completions:

```python
stream = await client.chat.completions.create(
    model=tier.model,
    messages=messages,
    stream=True,
)

async for chunk in stream:
    text = chunk.choices[0].delta.content
    if text:
        yield text
```

This preserves the existing `ModelRouter` contract for Moonshot, DeepSeek, Volcengine Ark,
Ollama, OpenAI, and other Chat Completions-compatible endpoints. No provider API selector or
Responses API adapter is added.

## 4. Protocol compatibility

The Extension/Gateway wire protocol increments from `2` to `3`.

- `POST /tasks/quick-insight` retains its current JSON shape and returns protocol version `3`.
- `POST /tasks/workspace` retains its URL but returns an NDJSON stream for protocol version `3`.
- Requests carrying protocol version `2` receive the existing `426 Upgrade Required` response.
- `WorkspaceResponse.protocol_version` becomes `3` inside the terminal `completed` event.
- A protocol-v3 Workspace request requires an Extension-generated UUID in `operationId`; Gateway
  validates it and echoes it as `operation_id` in every event.
- The Chrome storage schema remains `v2`; the final histories and artifacts shape is unchanged,
  so no local-state migration is performed.

The response media type is:

```http
Content-Type: application/x-ndjson; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no
X-Agent-Bridge-Protocol-Version: 3
```

## 5. Wire events

Every NDJSON line is one complete UTF-8 JSON object followed by `\n`. All stream events use a
Pydantic discriminated union, reject unknown fields, and include:

- `type`: stable event discriminator;
- `operation_id`: the validated Extension-generated request correlation UUID;
- `sequence`: a strictly increasing integer beginning at zero.

### 5.1 Started

```json
{
  "type": "started",
  "operation_id": "00000000-0000-0000-0000-000000000001",
  "sequence": 0,
  "created_at": "2026-07-20T12:00:00Z"
}
```

`started` is the first streamed event. Request schema validation, protocol validation,
authentication, resource normalization, rate limiting, Agent selection, and CV resolution happen
before it so those failures can still use ordinary HTTP status codes.

### 5.2 Status

```json
{
  "type": "status",
  "operation_id": "00000000-0000-0000-0000-000000000001",
  "sequence": 1,
  "stage": "generating_reply"
}
```

Allowed stages are:

- `routing`;
- `generating_reply`;
- `generating_artifact`;
- `finalizing`.

`artifact_type` is present only for `generating_artifact` and is `cv` or `cover_letter`.

### 5.3 Delta

```json
{
  "type": "delta",
  "operation_id": "00000000-0000-0000-0000-000000000001",
  "sequence": 2,
  "text": "这个岗"
}
```

`text` is the non-empty text fragment returned by one or more Chat Completion chunks. Deltas are
valid only for a `reply` plan. Artifact plans must never emit a delta.

### 5.4 Completed

```json
{
  "type": "completed",
  "operation_id": "00000000-0000-0000-0000-000000000001",
  "sequence": 9,
  "response": {
    "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
    "selected_action_id": "analyze",
    "result_type": "reply",
    "histories": [
      {
        "id": "00000000-0000-0000-0000-000000000002",
        "role": "user",
        "content": "这个岗位最看重什么？",
        "action_id": "analyze",
        "created_at": "2026-07-20T12:00:00Z",
        "attachments": []
      },
      {
        "id": "00000000-0000-0000-0000-000000000003",
        "role": "assistant",
        "content": "这个岗位最看重项目管理经验。",
        "action_id": "analyze",
        "created_at": "2026-07-20T12:00:01Z",
        "attachments": []
      }
    ],
    "artifacts": {"cv": null, "cover_letter": null},
    "meta": {
      "id": "00000000-0000-0000-0000-000000000004",
      "created_at": "2026-07-20T12:00:00Z",
      "status": "completed",
      "input_chars": 1200,
      "model": "configured-model",
      "started_at": "2026-07-20T12:00:00Z",
      "finished_at": "2026-07-20T12:00:01Z",
      "duration_ms": 1000
    },
    "protocol_version": 3
  }
}
```

`completed` is the only success terminal event. Its `response` is the same complete,
cross-validated `WorkspaceResponse` used today, apart from the protocol version.

### 5.5 Failed

```json
{
  "type": "failed",
  "operation_id": "00000000-0000-0000-0000-000000000001",
  "sequence": 4,
  "code": "model_error",
  "message": "Workspace generation failed",
  "recoverable": true
}
```

`failed` is the only failure terminal event after streaming has begun. Initial codes are:

- `model_error`;
- `invalid_model_output`;
- `stream_interrupted`;
- `internal_error`.

The public message remains bounded and does not include prompts, page contents, provider bodies,
keys, or tokens.

## 6. Gateway architecture

### 6.1 Model completion boundary

`OpenAIChatAgent` keeps its existing synchronous client for Quick Insight and adds cached
`AsyncOpenAI` clients keyed by the same `(url, key)` ModelTier identity.

The reusable asynchronous methods and stream value are:

```python
@dataclass(frozen=True)
class ModelTextStream:
    """Selected model and its provider-independent text chunks."""

    model: str
    chunks: AsyncIterator[str]


async def acomplete_prompt(*, system: str, prompt: str) -> tuple[str, str]: ...

async def open_prompt_stream(
    *, system: str, prompt: str
) -> ModelTextStream: ...
```

`acomplete_prompt()` is used for the small planning call. `open_prompt_stream()` is used for the
Specialist content call. No synchronous provider call runs on the ASGI event loop.

### 6.2 Agent stream interface

The Workspace execution contract becomes a streaming interface while Quick Insight remains
unchanged:

```python
class StreamingWorkspaceAgent(Protocol):
    """Stateless Agent capable of producing one streamed Workspace result."""

    def stream_chat(
        self, context: WorkspaceAgentContext
    ) -> AsyncIterator[AgentStreamEvent]:
        """Yield request-scoped progress, text deltas, and one complete ChatResult."""
```

Agent events contain business progress, Markdown deltas, and the final `ChatResult`. They do not
contain wire protocol versions, operation IDs, persistence metadata, HTTP errors, or Chrome state.
`TaskService` maps Agent events to wire events.

### 6.3 Job Match planning

`IntentRouter` becomes a `ChatPlanner` and returns one strict plan:

```python
class ChatPlan(BaseModel):
    specialist: SpecialistId
    output_mode: Literal["reply", "artifact"]
```

Validation enforces the legal matrix:

| Specialist | Reply | Artifact |
| --- | --- | --- |
| Job Analysis | yes | no |
| Resume | yes | yes, CV only |
| Cover Letter | yes | yes, Cover Letter only |
| General QA | yes | no |

The planning priority remains:

```text
current message > selected Action > complete histories > General QA
```

Quick Insight Actions remain deterministic and skip planning:

- Analyze -> Job Analysis reply;
- Tailor Resume -> CV artifact;
- Generate Cover Letter -> Cover Letter artifact.

### 6.4 Specialist output

Specialists no longer stream a JSON envelope.

- Reply mode streams raw Markdown and also accumulates it for final validation.
- Artifact mode streams raw draft Markdown into Gateway memory but exposes only status events.
- Artifact title and the short Assistant completion note are deterministic Agent-owned strings
  selected by artifact type, create/update state, and language.
- `JobMatchAgent` converts the completed content into the existing `ReplyResult`,
  `CreateArtifactResult`, or `UpdateArtifactResult` union.

This avoids incremental parsing of incomplete JSON and prevents Artifact drafts from leaking into
the UI before validation.

### 6.5 Summary Page

`SummaryPageAgent` always uses a reply plan. It streams raw Markdown directly and completes with
the existing `ReplyResult` shape. It does not use `ChatPlanner`.

### 6.6 Task Service and atomic reduction

`TaskService` owns the operation identity, event sequence, timing, metrics, and final reducer:

1. Validate and prepare request-scoped dependencies before streaming.
2. Emit `started`.
3. Consume and translate Agent events.
4. Accumulate the complete raw result in memory.
5. Revalidate the terminal `ChatResult`.
6. Allocate Message/Attachment/Artifact identity.
7. Run the existing Workspace reducer.
8. Validate the full `WorkspaceResponse`.
9. Persist one completed task record.
10. Emit `completed`.

An exception after `started` persists a failed operational record, emits one bounded `failed`
event, and never runs the reducer. Individual deltas are never persisted or logged.

### 6.7 API boundary

`api.py` remains responsible only for HTTP concerns. It prepares the stream through `TaskService`
and returns a Starlette `StreamingResponse`. Business generation, event construction, and metrics
remain in the service/Agent layers.

The API observes client disconnects and closes the OpenAI stream. A disconnected request cannot
emit `completed` or persist a successful transition.

## 7. Extension architecture

### 7.1 NDJSON parser

A small transport module owns incremental parsing:

```javascript
async function* readNdjson(response) { /* ... */ }
```

It uses `response.body.getReader()` plus `TextDecoder.decode(bytes, { stream: true })`, retains an
incomplete trailing line between reads, validates every parsed event, and rejects trailing invalid
JSON or a stream without exactly one terminal event.

### 7.2 Background stream coordinator

Background keeps one transient stream record per active resource operation:

```javascript
{
  operationId,
  tabId,
  storageKey,
  sequence,
  stage,
  markdown,
  submittedMessage,
  createdAt,
  abortController
}
```

The existing per-resource keyed queue remains the concurrency boundary. Background:

- reads Gateway delta events;
- appends `text` to its Markdown buffer;
- broadcasts cumulative snapshots rather than raw deltas;
- includes `operationId`, `sequence`, tab, and resource identity in every runtime event;
- applies only the validated terminal response;
- removes transient state after terminal success or failure.

Cumulative snapshots let a late Side Panel listener catch up without replaying every token.
`WORKSPACE_GET` includes the current in-memory stream snapshot when one exists, allowing a closed
and reopened Side Panel to resume rendering while Background continues the request.

### 7.3 Side Panel transient turn

Submitting a user message immediately creates:

```javascript
{
  operationId,
  actionId,
  userText,
  createdAt,
  assistantMarkdown: "",
  stage: "routing",
  failed: false
}
```

The Side Panel generates `operationId` with `crypto.randomUUID()` before dispatch. Quick Insight
Actions have their operation ID generated by Background before the Workspace request starts.
The Side Panel clears the composer, shows the User Message with local time, and shows an Assistant
placeholder. It renders cumulative Markdown snapshots through the existing Marked + DOMPurify
boundary, throttled to approximately 50 ms to avoid rebuilding the DOM for every small delta.

On `completed`, it validates and installs the complete canonical state, clears the transient turn,
and renders server-generated timestamps. It never locally appends the final User or Assistant
Message.

On `failed`, it keeps a visible failed Assistant state, restores the submitted text to the
composer, and leaves canonical state unchanged. Retry creates a new operation ID; it does not
reuse or persist the failed transient turn.

Quick Insight Actions have no transient User Message. Analyze streams an Assistant reply. Resume
and Cover Letter actions show localized generation status until the final Attachment appears.

### 7.4 Stale events and lifecycle

- A sequence not greater than the last accepted sequence is ignored.
- An event for another operation, tab, owner, or resource is ignored.
- Owner/token changes abort the stream and reuse the existing authenticated reset behavior.
- Switching tabs does not render the old tab's events.
- Closing only the Side Panel does not abort Background generation.
- Closing the originating tab aborts its active stream and clears its session mapping.
- The existing 120-second request timeout remains in the first release.

## 8. Reverse proxy

The Docker deployment uses Nginx in front of Gateway. Workspace streaming must not inherit
default proxy buffering. The deployment config adds a Workspace-specific unbuffered boundary (or
an equivalent shared proxy include) with at least:

```nginx
proxy_http_version 1.1;
proxy_buffering off;
proxy_cache off;
```

Gateway also emits `X-Accel-Buffering: no` and `Cache-Control: no-cache`. Tests must cover both the
application headers and the checked-in Nginx configuration so local success cannot mask a buffered
cloud deployment.

## 9. Error semantics

Before `started`, existing HTTP behavior remains authoritative:

- `400` invalid request/resource;
- `401` authentication required;
- `426` Extension update required;
- `429` rate limited;
- `502` request preparation failure.

After `started`, the HTTP status is already `200`, so every failure is represented by exactly one
`failed` event. A stream ending without `completed` or `failed` is treated by Extension as
`stream_interrupted`.

Partial Markdown is presentation-only. It is discarded on failure, is never added to histories,
and is never stored as an Artifact draft.

## 10. Testing

### 10.1 Gateway unit tests

- Async Chat Completions fake streams ignore empty chunks and yield text in order.
- ChatPlanner parses and validates the complete specialist/output-mode matrix.
- Gateway rejects an invalid `operationId` and echoes a valid one in every stream event.
- Quick Insight Actions bypass ChatPlanner with deterministic plans.
- Reply streams follow `started -> status -> delta* -> finalizing -> completed`.
- Artifact streams emit statuses but no deltas.
- Completed replies and artifacts preserve current reducer and version invariants.
- Model, planner, validation, and disconnect failures produce no completed reduction.
- NDJSON serialization produces one valid JSON object per line.

### 10.2 Gateway API tests

- Protocol v2 receives `426`; protocol v3 reaches the current route.
- Quick Insight still returns ordinary JSON with protocol version 3.
- Workspace returns NDJSON and the required anti-buffering headers.
- Pre-stream failures retain their HTTP status.
- Post-start failures finish with one `failed` event.
- A successful stream contains exactly one `started` and one `completed` event.

### 10.3 Extension tests

- NDJSON parser handles multiple lines in one network chunk.
- NDJSON parser handles one line split across chunks.
- `TextDecoder` preserves Chinese characters split across UTF-8 byte chunks.
- User Message appears immediately and composer text clears.
- Cumulative snapshots neither duplicate nor omit Markdown.
- Completed state removes transient UI and does not duplicate histories.
- Failed/interrupted streams restore input and preserve canonical state.
- Stale operation IDs and sequences are ignored.
- Artifact operations never render draft Markdown.
- Reopened Side Panel reads the current Background snapshot.
- Package verification includes every new runtime module.

### 10.4 Deployment and live acceptance

- Static deployment test confirms Workspace proxy buffering is disabled.
- A real normal reply displays at least one delta before `completed`.
- A real Artifact action displays status and only reveals its Attachment after completion.
- Reloading Side Panel after success shows only canonical persisted history.
- Gateway, Extension, package, and import test suites all pass.

## 11. Documentation and rollout

Implementation updates:

- `gateway/app/modules/task/README.md`;
- `gateway/app/agents/job_match/README.md`;
- `extension/README.md`;
- deployment documentation that describes the Nginx streaming boundary.

Gateway protocol v3 and the matching Extension must be deployed as one compatibility cutover.
Deploy Gateway first only if its v2 requests continue receiving the explicit update response and
the protocol-v3 Extension package is ready for installation. The manifest release version remains
independent from the wire integer and follows the existing Chrome Web Store release process.

## 12. Success criteria

The feature is complete when:

1. A user submission is visible immediately.
2. A normal Assistant reply visibly changes before the terminal response.
3. Artifact draft text never appears before successful completion.
4. No failure can alter canonical histories or artifacts.
5. Final state remains byte-for-byte valid under the existing Workspace schema invariants.
6. Local and Nginx-proxied requests both stream rather than buffer.
7. Protocol mismatch forces an Extension update instead of attempting mixed-version execution.
