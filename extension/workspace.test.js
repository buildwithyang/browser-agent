import { test } from "node:test";
import assert from "node:assert/strict";

import * as workspace from "./workspace.js";

const {
  ANONYMOUS_WORKSPACE_OWNER,
  applyWorkspaceResponse,
  canSend,
  canSendUserMessage,
  countUserTurns,
  createWorkspace,
  resetWorkspaceConversation,
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

/** Build one complete protocol-v4 HistoryMessage fixture. */
function history(index, overrides = {}) {
  const role = overrides.role || (index % 2 === 0 ? "user" : "assistant");
  return {
    id: fixtureId("3", index + 1),
    role,
    content: role === "user" ? "question" : "",
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
      history(0),
      history(1, { attachments: [first] }),
      history(2),
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
    protocol_version: 4,
    ...overrides,
  };
}

test("workspace key encodes schema v3, owner, and resource", () => {
  const first = workspaceStorageKey("u1", "https://x/a");
  assert.match(first, /^agent-bridge:workspace:v3:/);
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

test("createWorkspace persists only whitelisted schema-v3 fields", () => {
  const state = createWorkspace({
    resourceUrl: RESOURCE_URL,
    pageTitle: "Page",
    quickInsight: { title: "Insight" },
    shortcuts: [{ id: "analyze", title: "Analyze", prompt: "Analyze this role." }],
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    currentDocument: { kind: "note", text: "legacy draft" },
    updatedAt: "2026-07-19T00:00:00Z",
    selectedText: "private selection",
    pageText: "private page",
    imageText: "private image text",
  });

  assert.deepEqual(state, {
    schemaVersion: 3,
    resourceUrl: RESOURCE_URL,
    pageTitle: "Page",
    quickInsight: { title: "Insight" },
    shortcuts: [{ id: "analyze", title: "Analyze", prompt: "Analyze this role." }],
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    updatedAt: "2026-07-19T00:00:00Z",
  });
  assert.equal("currentDocument" in state, false);
});

test("resetWorkspaceConversation clears messages and Artifacts but preserves page metadata", () => {
  const current = artifactState();
  current.resourceUrl = RESOURCE_URL;
  current.pageTitle = "Platform Engineer";
  current.quickInsight = { title: "Strong match" };
  current.shortcuts = [{ id: "ask_more", title: "Ask More", prompt: "" }];
  current.updatedAt = "2026-07-20T10:00:00Z";

  const reset = resetWorkspaceConversation(current);

  assert.equal(reset.resourceUrl, RESOURCE_URL);
  assert.equal(reset.pageTitle, "Platform Engineer");
  assert.deepEqual(reset.quickInsight, { title: "Strong match" });
  assert.deepEqual(reset.shortcuts, current.shortcuts);
  assert.deepEqual(reset.histories, []);
  assert.deepEqual(reset.artifacts, { cv: null, cover_letter: null });
  assert.equal(reset.updatedAt, null);
  assert.equal(validateWorkspaceState(reset.histories, reset.artifacts), true);
  assert.notDeepEqual(current.histories, []);
});

test("Prompt Shortcuts require exactly id title prompt and allow empty Ask More", () => {
  const askMore = { id: "ask_more", title: "Ask More", prompt: "" };
  assert.deepEqual(createWorkspace({ shortcuts: [askMore] }).shortcuts, [askMore]);
  for (const shortcut of [
    { id: "ask_more", title: "Ask More" },
    { id: "ask_more", title: "Ask More", prompt: "", extra: true },
    { id: "", title: "Ask More", prompt: "" },
    { id: "ask_more", title: "", prompt: "" },
  ]) {
    assert.throws(() => createWorkspace({ shortcuts: [shortcut] }), /Shortcut/i);
  }
});

test("storage validation permits 20 paired records but rejects a 21st", () => {
  const histories = Array.from({ length: 20 }, (_, index) => history(index));
  assert.equal(validateWorkspaceState(histories, { cv: null, cover_letter: null }), true);
  assert.throws(
    () => validateWorkspaceState(
      [...histories, history(20, { role: "assistant", content: "surplus reply" })],
      { cv: null, cover_letter: null }
    ),
    /20 messages/
  );
});

test("canonical state accepts complete User Assistant pairs only", () => {
  for (const histories of [
    [history(0)],
    [history(1, { role: "assistant" })],
    [history(0), history(1, { role: "user" })],
  ]) {
    assert.throws(
      () => validateWorkspaceState(histories, { cv: null, cover_letter: null }),
      /User\/Assistant pairs/
    );
  }
});

test("canonical state rejects more than ten user histories", () => {
  const histories = Array.from({ length: 11 }, (_, index) => (
    history(index, { role: "user", content: `question ${index}` })
  ));

  assert.throws(
    () => validateWorkspaceState(histories, { cv: null, cover_letter: null }),
    /10 user/i
  );
});

test("pure v4 validator accepts IDs, UTC timestamps, opaque Markdown, and latest snapshots", () => {
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
      [
        history(4),
        history(5, { created_at: "2026-07-20T10:00:00+00:00", attachments: [cvAttachment] }),
      ],
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

test("v4 validator accepts canonical UUIDs without imposing version or variant bits", () => {
  const state = artifactState();
  state.histories[0].id = "30000000-0000-0000-0000-000000000001";
  assert.equal(validateWorkspaceState(state.histories, state.artifacts), true);
});

test("v4 validator rejects malformed IDs, timestamps, attachments, and fixed Artifact maps", () => {
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
  userAttachment.histories[1].role = "user";
  userAttachment.histories[1].content = "question";
  cases.push(userAttachment);

  const twoAttachments = copy(valid);
  twoAttachments.histories[1].attachments.push(
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

test("v4 validator enforces CV URLs, Artifact identity, type, uniqueness, and latest snapshot", () => {
  const valid = artifactState();
  const cases = [];

  const relativeCv = copy(valid);
  const cv = attachment({
    id: "20000000-0000-4000-8000-000000000003",
    artifactId: "10000000-0000-4000-8000-000000000002",
    type: "cv",
    content: "/relative/cv",
  });
  relativeCv.histories.push(history(4), history(5, { attachments: [cv] }));
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
  earlierWrongReference.histories[1].attachments[0].artifact_id =
    "10000000-0000-4000-8000-000000000099";
  cases.push(earlierWrongReference);

  const staleLatest = copy(valid);
  staleLatest.artifacts.cover_letter.attachment = staleLatest.histories[1].attachments[0];
  cases.push(staleLatest);

  const duplicateMessageId = copy(valid);
  duplicateMessageId.histories[1].id = duplicateMessageId.histories[0].id;
  cases.push(duplicateMessageId);

  const duplicateAttachmentId = copy(valid);
  duplicateAttachmentId.histories[3].attachments[0].id =
    duplicateAttachmentId.histories[1].attachments[0].id;
  duplicateAttachmentId.artifacts.cover_letter.attachment.id =
    duplicateAttachmentId.histories[1].attachments[0].id;
  cases.push(duplicateAttachmentId);

  for (const state of cases) {
    assert.throws(
      () => validateWorkspaceState(state.histories, state.artifacts),
      /Attachment|Artifact|message|URL|unique|type|latest/i
    );
  }
});

test("v4 validator rejects an Artifact version that differs from its latest Attachment", () => {
  const state = artifactState();
  state.histories = state.histories.slice(0, 2);
  state.artifacts.cover_letter.attachment = state.histories[1].attachments[0];
  state.artifacts.cover_letter.version = 2;

  assert.throws(
    () => validateWorkspaceState(state.histories, state.artifacts),
    /Artifact version must equal its Attachment version/
  );
});

test("allows the tenth user send after nine complete pairs", () => {
  const state = (turns) => ({
    histories: Array.from({ length: turns * 2 }, (_, index) => history(index)),
  });

  assert.equal(countUserTurns(state(9).histories), 9);
  assert.equal(canSendUserMessage(state(9)), true);
  assert.equal(countUserTurns(state(10).histories), 10);
  assert.equal(canSendUserMessage(state(10)), false);
  assert.equal(canSend(state(9)), true);
});

test("message-count guard requires a histories array", () => {
  assert.equal(canSendUserMessage({}), false);
  assert.equal(canSendUserMessage(null), false);
});

test("response atomically replaces complete histories and Artifacts", () => {
  const current = createWorkspace({
    resourceUrl: RESOURCE_URL,
    shortcuts: [{
      id: "write_cover_letter",
      title: "Write cover letter",
      prompt: "Write a cover letter.",
    }],
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    updatedAt: "old",
  });
  const before = copy(current);

  const next = applyWorkspaceResponse(current, workspaceResponse());

  assert.deepEqual(next.histories, artifactState().histories);
  assert.deepEqual(next.artifacts, artifactState().artifacts);
  assert.equal(next.resourceUrl, RESOURCE_URL);
  assert.equal("selectedActionId" in next, false);
  assert.equal(next.updatedAt, "2026-07-20T10:00:01+00:00");
  assert.deepEqual(current, before);
  assert.equal("currentDocument" in next, false);
});

test("completed response rejects more than ten user histories atomically", () => {
  const current = createWorkspace({ resourceUrl: RESOURCE_URL });
  const before = copy(current);
  const histories = Array.from({ length: 11 }, (_, index) => (
    history(index, { role: "user", content: `question ${index}` })
  ));

  assert.throws(
    () => applyWorkspaceResponse(current, workspaceResponse({
      result_type: "reply",
      histories,
      artifacts: { cv: null, cover_letter: null },
    })),
    /10 user/i
  );
  assert.deepEqual(current, before);
});

test("invalid complete response leaves the caller's prior object unchanged", () => {
  const current = createWorkspace({
    resourceUrl: RESOURCE_URL,
    shortcuts: [{ id: "analyze", title: "Analyze", prompt: "Analyze this role." }],
    histories: [],
    artifacts: { cv: null, cover_letter: null },
  });
  const before = copy(current);
  const invalid = workspaceResponse();
  invalid.artifacts.cover_letter.attachment = invalid.histories[1].attachments[0];

  assert.throws(() => applyWorkspaceResponse(current, invalid), /latest|Attachment/i);
  assert.deepEqual(current, before);

  assert.throws(
    () => applyWorkspaceResponse(current, { ...workspaceResponse(), document: null }),
    /exact|field|response/i
  );
  assert.deepEqual(current, before);

  for (const missing of [
    "resource_url",
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
