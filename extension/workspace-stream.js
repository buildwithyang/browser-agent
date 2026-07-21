import { applyWorkspaceResponse } from "./workspace.js";
import {
  assertGatewayBodyProtocol,
  assertGatewayProtocolResponse,
  readGatewayResponse,
} from "./workspace-controller.js";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STREAM_CONTENT_TYPE_PATTERN = /^application\/x-ndjson(?:\s*;|$)/i;
const STREAM_STAGES = new Set([
  "routing",
  "generating_reply",
  "generating_artifact",
  "finalizing",
]);
const ARTIFACT_TYPES = new Set(["cv", "cover_letter"]);
const FAILURE_CODES = new Set([
  "model_error",
  "invalid_model_output",
  "stream_interrupted",
  "internal_error",
]);
const DOCUMENT_TEXT_MAX_CHARS = 100_000;
const TITLE_MAX_CHARS = 500;

/** Return whether a value is one non-array JSON object. */
function isObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** Throw a stable transport schema error when one assertion is false. */
function requireStreamSchema(condition, message) {
  if (!condition) throw new TypeError(message);
}

/** Require an object to contain exactly one allowed wire-key set. */
function requireExactKeys(value, keys, label) {
  requireStreamSchema(isObject(value), `${label} must be an object`);
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  requireStreamSchema(
    actual.length === expected.length && actual.every((key, index) => key === expected[index]),
    `${label} must contain exactly ${expected.join(", ")}`
  );
}

/** Return whether a wire timestamp is one valid explicitly UTC instant. */
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

/** Validate the correlation and ordering fields shared by every stream event. */
function validateEventBase(value) {
  requireStreamSchema(
    typeof value.operation_id === "string" && UUID_PATTERN.test(value.operation_id),
    "Workspace stream operation_id must be a UUID"
  );
  requireStreamSchema(
    Number.isInteger(value.sequence) && value.sequence >= 0,
    "Workspace stream sequence must be a non-negative integer"
  );
}

/** Validate one status event and its stage-specific Artifact metadata. */
function validateStatusEvent(value) {
  const artifactStage = value.stage === "generating_artifact";
  if (artifactStage) {
    requireExactKeys(
      value,
      ["type", "operation_id", "sequence", "stage", "artifact_type"],
      "Workspace status event"
    );
    requireStreamSchema(
      ARTIFACT_TYPES.has(value.artifact_type),
      "Workspace status artifact_type is invalid"
    );
  } else {
    const keys = Object.prototype.hasOwnProperty.call(value, "artifact_type")
      ? ["type", "operation_id", "sequence", "stage", "artifact_type"]
      : ["type", "operation_id", "sequence", "stage"];
    requireExactKeys(value, keys, "Workspace status event");
    requireStreamSchema(
      value.artifact_type === undefined || value.artifact_type === null,
      "Workspace status artifact_type is valid only while generating an Artifact"
    );
  }
  requireStreamSchema(STREAM_STAGES.has(value.stage), "Workspace status stage is invalid");
}

/** Validate one strict protocol-v3 Workspace stream event without retaining state. */
export function validateWorkspaceStreamEvent(value) {
  requireStreamSchema(isObject(value), "Workspace stream event must be an object");
  requireStreamSchema(typeof value.type === "string", "Workspace stream event type is required");

  switch (value.type) {
    case "started":
      requireExactKeys(
        value,
        ["type", "operation_id", "sequence", "created_at"],
        "Workspace started event"
      );
      requireStreamSchema(
        isUtcTimestamp(value.created_at),
        "Workspace started created_at must be UTC"
      );
      break;
    case "status":
      validateStatusEvent(value);
      break;
    case "delta":
      requireExactKeys(
        value,
        ["type", "operation_id", "sequence", "text"],
        "Workspace delta event"
      );
      requireStreamSchema(
        typeof value.text === "string"
          && value.text.length >= 1
          && value.text.length <= DOCUMENT_TEXT_MAX_CHARS,
        "Workspace delta text is invalid"
      );
      break;
    case "completed":
      requireExactKeys(
        value,
        ["type", "operation_id", "sequence", "response"],
        "Workspace completed event"
      );
      requireStreamSchema(isObject(value.response), "Workspace completed response is invalid");
      assertGatewayBodyProtocol(value.response);
      // Reuse the canonical deep response validator without mutating or persisting local state.
      applyWorkspaceResponse({ resourceUrl: value.response.resource_url }, value.response);
      break;
    case "failed":
      requireExactKeys(
        value,
        ["type", "operation_id", "sequence", "code", "message", "recoverable"],
        "Workspace failed event"
      );
      requireStreamSchema(FAILURE_CODES.has(value.code), "Workspace failed code is invalid");
      requireStreamSchema(
        typeof value.message === "string"
          && value.message.length >= 1
          && value.message.length <= TITLE_MAX_CHARS,
        "Workspace failed message is invalid"
      );
      requireStreamSchema(
        typeof value.recoverable === "boolean",
        "Workspace failed recoverable flag is invalid"
      );
      break;
    default:
      throw new TypeError("Workspace stream event type is invalid");
  }

  validateEventBase(value);
  return value;
}

/** Validate protocol, status, media type, and ReadableStream availability before parsing. */
async function assertGatewayStreamResponse(response) {
  assertGatewayProtocolResponse(response);
  if (!response?.ok) {
    // The JSON response reader preserves 426 metadata and ordinary HTTP error semantics.
    await readGatewayResponse(response);
    throw new TypeError("Gateway returned an invalid Workspace stream response");
  }
  const contentType = response.headers?.get?.("Content-Type") ?? "";
  requireStreamSchema(
    STREAM_CONTENT_TYPE_PATTERN.test(contentType.trim()),
    "Gateway Workspace response Content-Type must be application/x-ndjson"
  );
  requireStreamSchema(
    response.body && typeof response.body.getReader === "function",
    "Gateway Workspace response body must be a ReadableStream"
  );
}

/** Validate one response stream using the protocol-v3 lifecycle state machine. */
class WorkspaceStreamLifecycle {
  constructor() {
    /** Track whether the optional routing stage was already observed. */
    this.routingSeen = false;
    /** Track the single active generation mode for delta and terminal validation. */
    this.generationStage = null;
    /** Track the Artifact type selected by an Artifact generation stage. */
    this.artifactType = null;
    /** Track whether generation advanced to the required finalizing stage. */
    this.finalizing = false;
  }

  /** Accept one validated event or reject a cross-event lifecycle violation. */
  accept(event) {
    if (event.type === "started" || event.type === "failed") return;
    if (event.type === "status") {
      this.#acceptStatus(event);
      return;
    }
    if (event.type === "delta") {
      requireStreamSchema(
        this.generationStage === "generating_reply" && !this.finalizing,
        "Workspace delta is invalid for the active mode"
      );
      return;
    }
    this.#acceptCompleted(event);
  }

  /** Advance through routing, one generation mode, and finalizing exactly once. */
  #acceptStatus(event) {
    if (event.stage === "routing") {
      requireStreamSchema(
        !this.routingSeen && this.generationStage === null && !this.finalizing,
        "Workspace routing status is out of order"
      );
      this.routingSeen = true;
      return;
    }
    if (event.stage === "generating_reply" || event.stage === "generating_artifact") {
      requireStreamSchema(
        this.generationStage === null && !this.finalizing,
        "Workspace generation status is out of order"
      );
      this.generationStage = event.stage;
      this.artifactType = event.artifact_type ?? null;
      return;
    }
    requireStreamSchema(
      this.generationStage !== null && !this.finalizing,
      "Workspace finalizing status is out of order"
    );
    this.finalizing = true;
  }

  /** Cross-check the completed result and terminal Attachment against generation mode. */
  #acceptCompleted(event) {
    requireStreamSchema(this.finalizing, "Workspace completed before finalizing");
    const response = event.response;
    if (this.generationStage === "generating_reply") {
      requireStreamSchema(
        response.result_type === "reply",
        "Workspace reply stream returned an Artifact result"
      );
      return;
    }
    requireStreamSchema(
      response.result_type === "create_artifact" || response.result_type === "update_artifact",
      "Workspace Artifact stream returned a reply result"
    );
    const terminalMessage = response.histories.at(-1);
    requireStreamSchema(
      terminalMessage?.attachments?.some((item) => item.type === this.artifactType),
      "Workspace Artifact result does not match the active Artifact type"
    );
  }
}

/** Parse, validate, and yield one strict incremental Workspace NDJSON event stream. */
export async function* readWorkspaceEventStream(response) {
  await assertGatewayStreamResponse(response);
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  let operationId = null;
  let previousSequence = -1;
  let terminalSeen = false;
  let terminalEvent = null;
  let readCompleted = false;
  const lifecycle = new WorkspaceStreamLifecycle();

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = done ? "" : lines.pop();

      for (const line of lines) {
        if (line === "") continue;
        const event = validateWorkspaceStreamEvent(JSON.parse(line));
        if (terminalSeen) {
          throw new TypeError("Workspace stream cannot contain events after a terminal event");
        }
        if (operationId === null) {
          requireStreamSchema(event.type === "started", "Workspace stream requires started first");
          requireStreamSchema(event.sequence === 0, "Workspace started sequence must be zero");
          operationId = event.operation_id;
        } else {
          requireStreamSchema(
            event.operation_id === operationId,
            "Workspace stream operation_id changed"
          );
          requireStreamSchema(
            event.sequence > previousSequence,
            "Workspace stream sequence must be strictly increasing"
          );
          requireStreamSchema(event.type !== "started", "Workspace stream may start only once");
        }
        previousSequence = event.sequence;
        lifecycle.accept(event);
        terminalSeen = event.type === "completed" || event.type === "failed";
        if (terminalSeen) {
          // Hold terminal success until EOF proves no trailing corruption or extra events exist.
          terminalEvent = event;
        } else {
          yield event;
        }
      }
      if (done) {
        readCompleted = true;
        break;
      }
    }

    requireStreamSchema(terminalSeen, "Workspace stream requires one terminal event");
    yield terminalEvent;
  } finally {
    if (!readCompleted) {
      try {
        await reader.cancel();
      } catch {
        // Preserve the original transport or validation failure.
      }
    }
    reader.releaseLock();
  }
}
