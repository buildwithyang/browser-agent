import { test } from "node:test";
import assert from "node:assert/strict";

import * as workspace from "./workspace.js";

const {
  ANONYMOUS_WORKSPACE_OWNER,
  applyWorkspaceResponse,
  canRunQuickInsightAction,
  canSend,
  canSendUserMessage,
  createWorkspace,
  validateWorkspaceState,
  workspaceStorageKey,
} = workspace;

const RESOURCE_URL = "https://x/job/1";
const ARTIFACT_ID = "10000000-0000-4000-8000-000000000001";
const ATTACHMENT_ONE_ID = "20000000-0000-4000-8000-000000000001";
const ATTACHMENT_TWO_ID = "20000000-0000-4000-8000-000000000002";

/** Return a deterministic UUID-shaped identifier for one fixture category and index. */
function fixtureId(category, index) {
  return `${category}0000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
}

/** Deep-copy one JSON wire fixture before changing a negative-test field. */
function copy(value) {
  return JSON.parse(JSON.stringify(value));
}

/** Build one complete protocol-v2 HistoryMessage fixture. */
function history(index, overrides = {}) {
  const role = overrides.role || (index % 2 === 0 ? "user" : "assistant");
  return {
    id: fixtureId("3", index + 1),
    role,
    content: role === "user" ? "question" : "",
    action_id: "analyze",
    created_at: "2026-07-20T10:00:00Z",
    attachments: [],
    ...overrides,
  };
}

/** Build one immutable Attachment snapshot. */
function attachment({
  id = ATTACHMENT_ONE_ID,
  artifactId = ARTIFACT_ID,
  version = 1,
  type = "cover_letter",
  title = "Cover Letter",
  content = "Dear Hiring Manager,\n\n**Opaque Markdown**",
} = {}) {
  return {
    id,
    artifact_id: artifactId,
    version,
    type,
    title,
    content,
  };
}

/** Build one valid state whose Artifact equals the latest same-type Attachment. */
function artifactState() {
  const first = attachment();
  const latest = attachment({
    id: ATTACHMENT_TWO_ID,
    version: 2,
    content: "# Latest letter\n\n<table>kept as text</table>",
  });
  return {
    histories: [
      history(1, { attachments: [first] }),
      history(3, { attachments: [latest] }),
    ],
    artifacts: {
      cv: null,
      cover_letter: {
        id: ARTIFACT_ID,
        type: "cover_letter",
        version: 2,
        title: "Cover Letter",
        draft: latest.content,
        attachment: latest,
      },
    },
  };
}

/** Build a response containing a complete canonical Workspace next state. */
function workspaceResponse(overrides = {}) {
  const state = artifactState();
  return {
    resource_url: RESOURCE_URL,
    selected_action_id: "write_cover_letter",
    result_type: "update_artifact",
    histories: state.histories,
    artifacts: state.artifacts,
    meta: {
      id: "40000000-0000-4000-8000-000000000001",
      created_at: "2026-07-20T10:00:01+00:00",
      status: "completed",
      input_chars: 123,
      model: "test-model",
      started_at: "2026-07-20T10:00:00Z",
      finished_at: "2026-07-20T10:00:01Z",
      duration_ms: 1000,
    },
    protocol_version: 2,
    ...overrides,
  };
}

test("workspace key encodes schema v2, owner, and resource", () => {
  const first = workspaceStorageKey("u1", "https://x/a");
  assert.match(first, /^agent-bridge:workspace:v2:/);
  assert.match(first, /u1/);
  assert.match(first, /https%3A%2F%2Fx%2Fa/);
  assert.notEqual(first, workspaceStorageKey("u2", "https://x/a"));
  assert.notEqual(first, workspaceStorageKey("u1", "https://x/b"));
});

test("workspace key uses the explicit anonymous owner and rejects blank resources", () => {
  assert.equal(
    workspaceStorageKey("", "https://x/a"),
    workspaceStorageKey(ANONYMOUS_WORKSPACE_OWNER, "https://x/a")
  );
  assert.throws(() => workspaceStorageKey("u1", ""), /resourceUrl/);
  assert.throws(() => workspaceStorageKey("u1", "   "), /resourceUrl/);
});

test("createWorkspace persists only whitelisted schema-v2 fields", () => {
  const state = createWorkspace({
    resourceUrl: RESOURCE_URL,
    pageTitle: "Page",
    quickInsight: { title: "Insight" },
    actions: [{ id: "analyze", title: "Analyze" }],
    defaultActionId: "analyze",
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    currentDocument: { kind: "note", text: "legacy draft" },
    updatedAt: "2026-07-19T00:00:00Z",
    selectedText: "private selection",
    pageText: "private page",
    imageText: "private image text",
  });

  assert.deepEqual(state, {
    schemaVersion: 2,
    resourceUrl: RESOURCE_URL,
    pageTitle: "Page",
    quickInsight: { title: "Insight" },
    actions: [{ id: "analyze", title: "Analyze" }],
    selectedActionId: "analyze",
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    updatedAt: "2026-07-19T00:00:00Z",
  });
  assert.equal("currentDocument" in state, false);
});

test("createWorkspace preserves a valid selected action before applying defaults", () => {
  const actions = [
    { id: "analyze", title: "Analyze" },
    { id: "ask_more", title: "Ask More" },
  ];
  assert.equal(
    createWorkspace({ actions, selectedActionId: "ask_more", defaultActionId: "analyze" })
      .selectedActionId,
    "ask_more"
  );
  assert.equal(
    createWorkspace({ actions, selectedActionId: "missing", defaultActionId: "analyze" })
      .selectedActionId,
    "analyze"
  );
});

test("pure v2 validator accepts IDs, UTC timestamps, opaque Markdown, and latest snapshots", () => {
  const state = artifactState();
  assert.equal(validateWorkspaceState(state.histories, state.artifacts), true);

  const cvAttachment = attachment({
    id: "20000000-0000-4000-8000-000000000003",
    artifactId: "10000000-0000-4000-8000-000000000002",
    type: "cv",
    content: "https://browser.buildwithyang.com/resumes/v1",
  });
  assert.equal(
    validateWorkspaceState(
      [history(5, { created_at: "2026-07-20T10:00:00+00:00", attachments: [cvAttachment] })],
      {
        cv: {
          id: cvAttachment.artifact_id,
          type: "cv",
          version: 1,
          title: "CV",
          draft: "# Full CV Markdown",
          attachment: cvAttachment,
        },
        cover_letter: null,
      }
    ),
    true
  );
});

test("v2 validator accepts canonical UUIDs without imposing version or variant bits", () => {
  const state = artifactState();
  state.histories[0].id = "30000000-0000-0000-0000-000000000001";
  assert.equal(validateWorkspaceState(state.histories, state.artifacts), true);
});

test("v2 validator rejects malformed IDs, timestamps, attachments, and fixed Artifact maps", () => {
  const valid = artifactState();
  const cases = [];

  const badMessageId = copy(valid);
  badMessageId.histories[0].id = "not-a-uuid";
  cases.push(badMessageId);

  const localTimestamp = copy(valid);
  localTimestamp.histories[0].created_at = "2026-07-20T14:00:00+04:00";
  cases.push(localTimestamp);

  const impossibleTimestamp = copy(valid);
  impossibleTimestamp.histories[0].created_at = "2026-02-30T10:00:00Z";
  cases.push(impossibleTimestamp);

  const userAttachment = copy(valid);
  userAttachment.histories[0].role = "user";
  userAttachment.histories[0].content = "question";
  cases.push(userAttachment);

  const twoAttachments = copy(valid);
  twoAttachments.histories[0].attachments.push(
    attachment({ id: "20000000-0000-4000-8000-000000000099" })
  );
  cases.push(twoAttachments);

  const missingArtifactKey = copy(valid);
  delete missingArtifactKey.artifacts.cv;
  cases.push(missingArtifactKey);

  const extraArtifactKey = copy(valid);
  extraArtifactKey.artifacts.other = null;
  cases.push(extraArtifactKey);

  for (const state of cases) {
    assert.throws(
      () => validateWorkspaceState(state.histories, state.artifacts),
      /Workspace|message|Attachment|Artifact|UTC|UUID/i
    );
  }
});

test("v2 validator enforces CV URLs, Artifact identity, type, uniqueness, and latest snapshot", () => {
  const valid = artifactState();
  const cases = [];

  const relativeCv = copy(valid);
  const cv = attachment({
    id: "20000000-0000-4000-8000-000000000003",
    artifactId: "10000000-0000-4000-8000-000000000002",
    type: "cv",
    content: "/relative/cv",
  });
  relativeCv.histories.push(history(5, { attachments: [cv] }));
  relativeCv.artifacts.cv = {
    id: cv.artifact_id,
    type: "cv",
    version: 1,
    title: "CV",
    draft: "# CV",
    attachment: cv,
  };
  cases.push(relativeCv);

  const wrongType = copy(valid);
  wrongType.artifacts.cover_letter.type = "cv";
  cases.push(wrongType);

  const wrongReference = copy(valid);
  wrongReference.artifacts.cover_letter.attachment.artifact_id =
    "10000000-0000-4000-8000-000000000099";
  cases.push(wrongReference);

  const earlierWrongReference = copy(valid);
  earlierWrongReference.histories[0].attachments[0].artifact_id =
    "10000000-0000-4000-8000-000000000099";
  cases.push(earlierWrongReference);

  const staleLatest = copy(valid);
  staleLatest.artifacts.cover_letter.attachment = staleLatest.histories[0].attachments[0];
  cases.push(staleLatest);

  const duplicateMessageId = copy(valid);
  duplicateMessageId.histories[1].id = duplicateMessageId.histories[0].id;
  cases.push(duplicateMessageId);

  const duplicateAttachmentId = copy(valid);
  duplicateAttachmentId.histories[1].attachments[0].id =
    duplicateAttachmentId.histories[0].attachments[0].id;
  duplicateAttachmentId.artifacts.cover_letter.attachment.id =
    duplicateAttachmentId.histories[0].attachments[0].id;
  cases.push(duplicateAttachmentId);

  for (const state of cases) {
    assert.throws(
      () => validateWorkspaceState(state.histories, state.artifacts),
      /Attachment|Artifact|message|URL|unique|type|latest/i
    );
  }
});

test("message-count guards model the two request-trigger boundaries", () => {
  const state = (length) => ({
    schemaVersion: 2,
    histories: Array.from({ length }, (_, index) => history(index)),
    artifacts: { cv: null, cover_letter: null },
  });

  assert.equal(canSendUserMessage(state(9)), true);
  assert.equal(canSendUserMessage(state(10)), false);
  assert.equal(canRunQuickInsightAction(state(10)), true);
  assert.equal(canRunQuickInsightAction(state(11)), false);
  assert.equal(canSend(state(9)), true, "legacy UI alias follows user-message semantics");
});

test("message-count guards fail closed when any nested state is invalid", () => {
  const invalid = {
    schemaVersion: 2,
    histories: [history(0, { created_at: "2026-07-20T14:00:00+04:00" })],
    artifacts: { cv: null, cover_letter: null },
  };
  assert.equal(canSendUserMessage(invalid), false);
  assert.equal(canRunQuickInsightAction(invalid), false);
  assert.equal(canSendUserMessage({}), false);
});

test("response atomically replaces complete histories and Artifacts", () => {
  const current = createWorkspace({
    resourceUrl: RESOURCE_URL,
    actions: [{ id: "write_cover_letter", title: "Write cover letter" }],
    selectedActionId: "write_cover_letter",
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    updatedAt: "old",
  });
  const before = copy(current);

  const next = applyWorkspaceResponse(current, workspaceResponse());

  assert.deepEqual(next.histories, artifactState().histories);
  assert.deepEqual(next.artifacts, artifactState().artifacts);
  assert.equal(next.resourceUrl, RESOURCE_URL);
  assert.equal(next.selectedActionId, "write_cover_letter");
  assert.equal(next.updatedAt, "2026-07-20T10:00:01+00:00");
  assert.deepEqual(current, before);
  assert.equal("currentDocument" in next, false);
});

test("invalid complete response leaves the caller's prior object unchanged", () => {
  const current = createWorkspace({
    resourceUrl: RESOURCE_URL,
    actions: [{ id: "analyze", title: "Analyze" }],
    histories: [],
    artifacts: { cv: null, cover_letter: null },
  });
  const before = copy(current);
  const invalid = workspaceResponse();
  invalid.artifacts.cover_letter.attachment = invalid.histories[0].attachments[0];

  assert.throws(() => applyWorkspaceResponse(current, invalid), /latest|Attachment/i);
  assert.deepEqual(current, before);

  assert.throws(
    () => applyWorkspaceResponse(current, { ...workspaceResponse(), document: null }),
    /exact|field|response/i
  );
  assert.deepEqual(current, before);

  for (const missing of [
    "resource_url",
    "selected_action_id",
    "result_type",
    "histories",
    "artifacts",
    "protocol_version",
  ]) {
    const response = workspaceResponse();
    delete response[missing];
    assert.throws(() => applyWorkspaceResponse(current, response));
    assert.deepEqual(current, before);
  }

  assert.throws(
    () => applyWorkspaceResponse(current, workspaceResponse({ resource_url: "https://x/job/2" })),
    /resource/i
  );
  assert.deepEqual(current, before);
});

test("response rejects incomplete or invalid Gateway execution metadata", () => {
  const current = createWorkspace({ resourceUrl: RESOURCE_URL });
  const invalidMeta = [
    { id: "not-a-uuid" },
    { created_at: "2026-07-20T14:00:00+04:00" },
    { status: "failed" },
    { input_chars: 1.5 },
    { model: 123 },
    { started_at: "local-time" },
    { finished_at: "local-time" },
    { duration_ms: 1.5 },
  ];

  for (const change of invalidMeta) {
    const response = workspaceResponse();
    Object.assign(response.meta, change);
    assert.throws(() => applyWorkspaceResponse(current, response), /meta|UUID|UTC|status|model/i);
  }

  const response = workspaceResponse();
  delete response.meta.model;
  assert.throws(() => applyWorkspaceResponse(current, response), /meta/i);
});
