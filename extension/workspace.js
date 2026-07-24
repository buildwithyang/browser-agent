import { EXTENSION_PROTOCOL_VERSION } from "./config.js";

/** The explicit owner used by self-hosted extensions without authentication. */
export const ANONYMOUS_WORKSPACE_OWNER = "anonymous";

/** The local Workspace schema version, independent from Extension release versions. */
export const WORKSPACE_SCHEMA_VERSION = 3;
export const MAX_WORKSPACE_TURNS = 10;
export const MAX_WORKSPACE_HISTORIES = MAX_WORKSPACE_TURNS * 2;

const WORKSPACE_STORAGE_PREFIX = `agent-bridge:workspace:v${WORKSPACE_SCHEMA_VERSION}`;
const USER_HISTORY_CONTENT_MAX_CHARS = 10_000;
const DOCUMENT_TEXT_MAX_CHARS = 100_000;
const CV_ATTACHMENT_CONTENT_MAX_CHARS = 4_096;
const TITLE_MAX_CHARS = 500;
const ARTIFACT_VERSION_MAX = 2_147_483_647;
const ARTIFACT_TYPES = new Set(["cv", "cover_letter"]);
const RESULT_TYPES = new Set(["reply", "create_artifact", "update_artifact"]);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Return a stable owner id without deriving identity from a bearer token. */
function normalizedOwnerId(ownerId) {
  return typeof ownerId === "string" && ownerId.trim()
    ? ownerId.trim()
    : ANONYMOUS_WORKSPACE_OWNER;
}

/** Return whether a value is a non-array object with the default JSON shape. */
function isObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** Throw a stable schema error when one assertion is false. */
function requireSchema(condition, message) {
  if (!condition) throw new TypeError(message);
}

/** Require an object to contain exactly the named wire keys. */
function requireExactKeys(value, keys, label) {
  requireSchema(isObject(value), `${label} must be an object`);
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  requireSchema(
    actual.length === expected.length && actual.every((key, index) => key === expected[index]),
    `${label} must contain exactly ${expected.join(", ")}`
  );
}

/** Validate one server-declared editable Prompt Shortcut. */
export function validatePromptShortcut(shortcut) {
  requireExactKeys(shortcut, ["id", "title", "prompt"], "Prompt Shortcut");
  requireSchema(typeof shortcut.id === "string" && !!shortcut.id.trim(), "Shortcut id is invalid");
  requireSchema(
    typeof shortcut.title === "string" && shortcut.title.length >= 1
      && shortcut.title.length <= TITLE_MAX_CHARS,
    "Shortcut title is invalid"
  );
  requireSchema(
    typeof shortcut.prompt === "string" && shortcut.prompt.length <= USER_HISTORY_CONTENT_MAX_CHARS,
    "Shortcut prompt is invalid"
  );
  return true;
}

/** Return whether a string is one canonical JSON UUID value. */
function isUuid(value) {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

/** Return whether a wire timestamp represents UTC explicitly. */
function isUtcTimestamp(value) {
  if (typeof value !== "string") return false;
  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-]00:00)$/
  );
  if (!match) return false;
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return false;
  const [, year, month, day, hour, minute, second] = match.map(Number);
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() + 1 === month
    && parsed.getUTCDate() === day
    && parsed.getUTCHours() === hour
    && parsed.getUTCMinutes() === minute
    && parsed.getUTCSeconds() === second;
}

/** Validate one immutable Artifact Attachment without interpreting Markdown. */
function validateAttachment(value) {
  requireExactKeys(
    value,
    ["id", "artifact_id", "version", "type", "title", "content"],
    "Attachment"
  );
  requireSchema(isUuid(value.id), "Attachment id must be a UUID");
  requireSchema(isUuid(value.artifact_id), "Attachment artifact_id must be a UUID");
  requireSchema(
    Number.isInteger(value.version)
      && value.version >= 1
      && value.version <= ARTIFACT_VERSION_MAX,
    "Attachment version is invalid"
  );
  requireSchema(ARTIFACT_TYPES.has(value.type), "Attachment type is invalid");
  requireSchema(
    typeof value.title === "string"
      && value.title.length >= 1
      && value.title.length <= TITLE_MAX_CHARS,
    "Attachment title is invalid"
  );
  requireSchema(
    typeof value.content === "string"
      && value.content.length >= 1
      && value.content.length <= DOCUMENT_TEXT_MAX_CHARS,
    "Attachment content is invalid"
  );
  if (value.type === "cv") {
    let parsed = null;
    try {
      parsed = new URL(value.content);
    } catch {
      // The assertion below produces one stable schema error.
    }
    requireSchema(
      value.content === value.content.trim()
        && value.content.length <= CV_ATTACHMENT_CONTENT_MAX_CHARS
        && !!parsed
        && (parsed.protocol === "http:" || parsed.protocol === "https:")
        && !!parsed.host,
      "CV Attachment content must be an absolute HTTP(S) URL"
    );
  }
}

/** Validate one complete HistoryMessage, including role-specific Attachment rules. */
function validateHistoryMessage(message) {
  requireExactKeys(
    message,
    ["id", "role", "content", "created_at", "attachments"],
    "Workspace message"
  );
  requireSchema(isUuid(message.id), "Workspace message id must be a UUID");
  requireSchema(
    message.role === "user" || message.role === "assistant",
    "Workspace message role is invalid"
  );
  requireSchema(typeof message.content === "string", "Workspace message content is invalid");
  if (message.role === "user") {
    requireSchema(
      message.content.length >= 1 && message.content.length <= USER_HISTORY_CONTENT_MAX_CHARS,
      "User Workspace message content is invalid"
    );
  } else {
    requireSchema(
      message.content.length <= DOCUMENT_TEXT_MAX_CHARS,
      "Assistant Workspace message content is invalid"
    );
  }
  requireSchema(isUtcTimestamp(message.created_at), "Workspace message created_at must be UTC");
  requireSchema(Array.isArray(message.attachments), "Workspace message attachments must be an array");
  requireSchema(message.attachments.length <= 1, "Workspace message has too many Attachments");
  requireSchema(
    message.role !== "user" || message.attachments.length === 0,
    "User Workspace message Attachments must be empty"
  );
  for (let index = 0; index < message.attachments.length; index += 1) {
    requireSchema(index in message.attachments, "Workspace message Attachments cannot be sparse");
    validateAttachment(message.attachments[index]);
  }
}

/** Validate one latest Artifact snapshot and its embedded Attachment. */
function validateArtifact(artifact) {
  requireExactKeys(
    artifact,
    ["id", "type", "version", "title", "draft", "attachment"],
    "Artifact"
  );
  requireSchema(isUuid(artifact.id), "Artifact id must be a UUID");
  requireSchema(ARTIFACT_TYPES.has(artifact.type), "Artifact type is invalid");
  requireSchema(
    Number.isInteger(artifact.version)
      && artifact.version >= 1
      && artifact.version <= ARTIFACT_VERSION_MAX,
    "Artifact version is invalid"
  );
  requireSchema(
    typeof artifact.title === "string"
      && artifact.title.length >= 1
      && artifact.title.length <= TITLE_MAX_CHARS,
    "Artifact title is invalid"
  );
  requireSchema(
    typeof artifact.draft === "string" && artifact.draft.length <= DOCUMENT_TEXT_MAX_CHARS,
    "Artifact draft is invalid"
  );
  validateAttachment(artifact.attachment);
}

/** Return whether two validated Attachment snapshots are byte-for-field identical. */
function attachmentsEqual(left, right) {
  return left.id === right.id
    && left.artifact_id === right.artifact_id
    && left.version === right.version
    && left.type === right.type
    && left.title === right.title
    && left.content === right.content;
}

/** Validate the complete ExecutionMeta emitted by a successful Workspace transition. */
function validateExecutionMeta(meta) {
  requireExactKeys(
    meta,
    [
      "id",
      "created_at",
      "status",
      "input_chars",
      "model",
      "started_at",
      "finished_at",
      "duration_ms",
    ],
    "Workspace response meta"
  );
  requireSchema(isUuid(meta.id), "Workspace response meta id must be a UUID");
  requireSchema(isUtcTimestamp(meta.created_at), "Workspace response meta created_at must be UTC");
  requireSchema(meta.status === "completed", "Workspace response meta status must be completed");
  requireSchema(Number.isInteger(meta.input_chars), "Workspace response meta input_chars is invalid");
  requireSchema(typeof meta.model === "string", "Workspace response meta model is invalid");
  requireSchema(
    meta.started_at === null || isUtcTimestamp(meta.started_at),
    "Workspace response meta started_at must be UTC or null"
  );
  requireSchema(
    meta.finished_at === null || isUtcTimestamp(meta.finished_at),
    "Workspace response meta finished_at must be UTC or null"
  );
  requireSchema(
    meta.duration_ms === null || Number.isInteger(meta.duration_ms),
    "Workspace response meta duration_ms is invalid"
  );
}

/** Validate the complete storage-schema-v3 Workspace graph without mutating it. */
export function validateWorkspaceState(histories, artifacts) {
  requireSchema(Array.isArray(histories), "Workspace histories must be an array");
  requireSchema(
    histories.length <= MAX_WORKSPACE_HISTORIES,
    `Workspace histories must contain at most ${MAX_WORKSPACE_HISTORIES} messages`
  );
  requireSchema(
    countUserTurns(histories) <= MAX_WORKSPACE_TURNS,
    `Workspace histories must contain at most ${MAX_WORKSPACE_TURNS} user messages`
  );
  requireSchema(
    histories.length % 2 === 0
      && histories.every((message, index) => (
        message?.role === (index % 2 === 0 ? "user" : "assistant")
      )),
    "Workspace histories must contain complete User/Assistant pairs"
  );
  requireExactKeys(artifacts, ["cv", "cover_letter"], "Workspace Artifacts");

  const messageIds = new Set();
  const attachmentIds = new Set();
  const attachments = [];
  const latestByType = new Map();
  for (let index = 0; index < histories.length; index += 1) {
    requireSchema(index in histories, "Workspace histories cannot be sparse");
    const message = histories[index];
    validateHistoryMessage(message);
    requireSchema(!messageIds.has(message.id), "Workspace message IDs must be unique");
    messageIds.add(message.id);
    for (const item of message.attachments) {
      requireSchema(!attachmentIds.has(item.id), "Attachment IDs must be unique");
      attachmentIds.add(item.id);
      attachments.push(item);
      latestByType.set(item.type, item);
    }
  }

  const artifactIds = new Set();
  for (const type of ARTIFACT_TYPES) {
    const artifact = artifacts[type];
    requireSchema(artifact === null || isObject(artifact), `Artifact ${type} must be nullable`);
    if (artifact === null) continue;
    validateArtifact(artifact);
    requireSchema(artifact.type === type, "Artifact type must match its fixed key");
    requireSchema(!artifactIds.has(artifact.id), "Artifact IDs must be unique");
    artifactIds.add(artifact.id);
    requireSchema(
      artifact.attachment.artifact_id === artifact.id,
      "Artifact Attachment must reference its Artifact"
    );
    requireSchema(
      artifact.version === artifact.attachment.version,
      "Artifact version must equal its Attachment version"
    );
    const latest = latestByType.get(type);
    requireSchema(
      !!latest && attachmentsEqual(latest, artifact.attachment),
      "Artifact Attachment must equal the latest Attachment of its type"
    );
  }

  for (const item of attachments) {
    const artifact = artifacts[item.type];
    requireSchema(
      artifact !== null && item.artifact_id === artifact.id,
      "Attachment artifact_id must reference its current Artifact"
    );
  }
  return true;
}

/** Return an owner- and resource-scoped, schema-versioned chrome.storage.local key. */
export function workspaceStorageKey(ownerId, resourceUrl) {
  if (typeof resourceUrl !== "string" || !resourceUrl.trim()) {
    throw new TypeError("resourceUrl must be a non-empty string");
  }
  return [
    WORKSPACE_STORAGE_PREFIX,
    encodeURIComponent(normalizedOwnerId(ownerId)),
    encodeURIComponent(resourceUrl.trim()),
  ].join(":");
}

/** Copy only the two fixed Artifact slots into local state. */
function localArtifacts(value) {
  const source = isObject(value) ? value : {};
  return {
    cv: source.cv ?? null,
    cover_letter: source.cover_letter ?? null,
  };
}

/** Create the privacy-bounded local Workspace schema-v3 state. */
export function createWorkspace(seed = {}) {
  const shortcuts = Array.isArray(seed.shortcuts) ? seed.shortcuts.map((shortcut) => ({ ...shortcut })) : [];
  shortcuts.forEach(validatePromptShortcut);
  return {
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    resourceUrl: typeof seed.resourceUrl === "string" ? seed.resourceUrl : "",
    pageTitle: typeof seed.pageTitle === "string" ? seed.pageTitle : "",
    quickInsight: seed.quickInsight ?? null,
    shortcuts,
    histories: Array.isArray(seed.histories) ? [...seed.histories] : [],
    artifacts: localArtifacts(seed.artifacts),
    updatedAt: seed.updatedAt ?? null,
  };
}

/** Reset conversation-owned messages and Artifacts while preserving page discovery metadata. */
export function resetWorkspaceConversation(state) {
  const current = createWorkspace(state);
  return createWorkspace({
    ...current,
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    updatedAt: null,
  });
}

/** Validate and atomically replace canonical Workspace fields from one complete response. */
export function applyWorkspaceResponse(state, response) {
  const current = createWorkspace(state);
  requireExactKeys(
    response,
    [
      "resource_url",
      "result_type",
      "histories",
      "artifacts",
      "meta",
      "protocol_version",
    ],
    "Workspace response"
  );
  requireSchema(
    typeof response.resource_url === "string" && !!response.resource_url.trim(),
    "Workspace response resource URL is required"
  );
  requireSchema(
    !current.resourceUrl || response.resource_url === current.resourceUrl,
    "Workspace response resource URL does not match the current Workspace"
  );
  requireSchema(RESULT_TYPES.has(response.result_type), "Workspace response result type is invalid");
  requireSchema(
    response.protocol_version === EXTENSION_PROTOCOL_VERSION,
    "Workspace response protocol version is invalid"
  );
  validateExecutionMeta(response.meta);
  validateWorkspaceState(response.histories, response.artifacts);

  // Construct only after every nested invariant passes so the caller's old object stays untouched.
  return {
    ...current,
    resourceUrl: response.resource_url,
    histories: [...response.histories],
    artifacts: localArtifacts(response.artifacts),
    updatedAt: response.meta.created_at,
  };
}

/** Count canonical user messages independently from Assistant output records. */
export function countUserTurns(histories = []) {
  return Array.isArray(histories)
    ? histories.reduce((count, message) => count + (message?.role === "user" ? 1 : 0), 0)
    : 0;
}

/** Return whether one valid v3 state can append another user message. */
export function canSendUserMessage(state) {
  return Array.isArray(state?.histories)
    && countUserTurns(state.histories) < MAX_WORKSPACE_TURNS;
}

/** Preserve the compact Side Panel send-guard API. */
export function canSend(state) {
  return canSendUserMessage(state);
}
