const QUICK_INSIGHT_ACTION_IDS = new Map([
  ["analyze", "analyze"],
  ["tailor_resume", "tailor_resume"],
  ["write_cover_letter", "write_cover_letter"],
  // Accept the product-label alias while emitting the Gateway's stable Action ID.
  ["generate_cover_letter", "write_cover_letter"],
]);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Error raised when a validated stream terminates without a canonical response. */
export class WorkspaceStreamFailedError extends Error {
  /** Retain only bounded routing metadata, never the Gateway's provider-facing message. */
  constructor(code = "stream_interrupted", recoverable = true) {
    super("Workspace generation failed. Please retry.");
    this.name = "WorkspaceStreamFailedError";
    this.code = code;
    this.recoverable = recoverable;
  }
}

/** Error raised when an operation loses ownership before its stream can be applied. */
export class WorkspaceOperationStaleError extends Error {
  /** Mark stale work so Background can answer its caller without broadcasting it to newer UI. */
  constructor() {
    super("The Workspace operation was superseded.");
    this.name = "WorkspaceOperationStaleError";
    this.suppressBroadcast = true;
  }
}

/** Return a non-empty Action ID or throw one stable command-validation error. */
function requiredActionId(actionId) {
  if (typeof actionId !== "string" || !actionId.trim()) {
    throw new TypeError("Workspace Action ID is required");
  }
  return actionId.trim();
}

/** Describe one Quick Insight Action Workspace operation without performing side effects. */
export function createQuickInsightOperation(actionId) {
  const commandActionId = requiredActionId(actionId);
  if (commandActionId === "ask_more") {
    return Object.freeze({
      kind: "open_only",
      trigger: null,
      actionId: commandActionId,
    });
  }
  const gatewayActionId = QUICK_INSIGHT_ACTION_IDS.get(commandActionId);
  if (!gatewayActionId) {
    throw new TypeError(`Unsupported Quick Insight Action: ${commandActionId}`);
  }
  return Object.freeze({
    kind: "request",
    trigger: "quick_insight_action",
    actionId: gatewayActionId,
  });
}

/** Describe one validated composer Workspace operation without performing side effects. */
export function createUserMessageOperation(actionId, message, operationId = null) {
  const submittedMessage = typeof message === "string" ? message : "";
  const userMessage = submittedMessage.trim();
  if (!userMessage) throw new TypeError("Message cannot be empty");
  const operation = {
    kind: "request",
    trigger: "user_message",
    actionId: requiredActionId(actionId),
    message: userMessage,
    submittedMessage,
  };
  if (operationId !== null) operation.operationId = operationId;
  return Object.freeze(operation);
}

/** Bind one request Command to the exact Extension-generated UUID used on the wire. */
export function identifyWorkspaceOperation(operation, operationId) {
  if (!operation || operation.kind !== "request") {
    throw new TypeError("Only request operations can be identified");
  }
  if (typeof operationId !== "string" || !UUID_PATTERN.test(operationId)) {
    throw new TypeError("Workspace operationId must be a UUID");
  }
  return Object.freeze({ ...operation, operationId });
}

/** Return one immutable cumulative snapshot after applying a validated stream event. */
function advanceStreamSnapshot(snapshot, event) {
  return Object.freeze({
    operationId: snapshot.operationId,
    sequence: event.sequence,
    stage: event.type === "status" ? event.stage : snapshot.stage,
    markdown: event.type === "delta"
      ? snapshot.markdown + event.text
      : snapshot.markdown,
    createdAt: event.type === "started" ? event.created_at : snapshot.createdAt,
  });
}

/** Build one stable cancellation error without exposing an AbortSignal reason string. */
function workspaceAbortError() {
  return new DOMException("Workspace operation aborted", "AbortError");
}

/** Lazily start one coordinator boundary and race it against generation cancellation. */
function awaitWorkspaceBoundary(operation, signal) {
  if (signal?.aborted) return Promise.reject(workspaceAbortError());
  let value;
  try {
    value = operation();
  } catch (error) {
    return Promise.reject(error);
  }
  if (!signal) return Promise.resolve(value);
  return new Promise((resolve, reject) => {
    /** Reject this boundary exactly once when the active generation is canceled. */
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      reject(workspaceAbortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
    Promise.resolve(value).then(
      (result) => {
        signal.removeEventListener("abort", onAbort);
        resolve(result);
      },
      (error) => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      }
    );
  });
}

/** Yield an async stream while racing every pending iterator read against cancellation. */
async function* abortableWorkspaceStream(stream, signal) {
  const iterator = stream[Symbol.asyncIterator]();
  let exhausted = false;
  try {
    while (true) {
      const next = await awaitWorkspaceBoundary(() => iterator.next(), signal);
      if (next.done) {
        exhausted = true;
        return;
      }
      yield next.value;
    }
  } finally {
    if (!exhausted && typeof iterator.return === "function") {
      const close = Promise.resolve(iterator.return()).catch(() => undefined);
      // A transport ignoring AbortSignal must not retain ownership of the keyed queue.
      if (!signal?.aborted) await close;
    }
  }
}

/** Run one request Command as a strict event stream inside its keyed queue. */
export async function runWorkspaceOperation(operation, dependencies) {
  if (!operation || operation.kind === "open_only") return null;
  if (operation.kind !== "request") throw new TypeError("Unknown Workspace operation kind");
  const {
    queue,
    key,
    loadLatest,
    collectPageContext,
    buildRequest,
    executeRequest,
    onEvent,
    applyResponse,
    signal,
  } = dependencies || {};
  if (!queue?.run || !key) throw new TypeError("Workspace operation queue and key are required");
  if (typeof operation.operationId !== "string" || !UUID_PATTERN.test(operation.operationId)) {
    throw new TypeError("Workspace operationId must be a UUID");
  }

  return queue.run(key, async () => {
    // The click-time object is intentionally ignored; queue ordering makes only this reload current.
    const latest = await awaitWorkspaceBoundary(() => loadLatest(), signal);
    const pageContext = await awaitWorkspaceBoundary(() => collectPageContext(), signal);
    const body = buildRequest(pageContext, latest, operation);
    if (body?.operationId !== operation.operationId) {
      throw new TypeError("Workspace request operationId does not match its operation");
    }
    const stream = await awaitWorkspaceBoundary(
      () => executeRequest(body, latest, operation),
      signal
    );
    if (!stream || typeof stream[Symbol.asyncIterator] !== "function") {
      throw new TypeError("Workspace request must return an async event stream");
    }

    let snapshot = Object.freeze({
      operationId: operation.operationId,
      sequence: -1,
      stage: null,
      markdown: "",
      createdAt: null,
    });
    let terminalEvent = null;
    let terminalSnapshot = null;
    for await (const event of abortableWorkspaceStream(stream, signal)) {
      if (!event || event.operation_id !== operation.operationId) {
        throw new TypeError("Workspace stream operation identity does not match the request");
      }
      if (!Number.isInteger(event.sequence) || event.sequence <= snapshot.sequence) {
        throw new TypeError("Workspace stream sequence is stale");
      }
      if (snapshot.sequence === -1 && (event.type !== "started" || event.sequence !== 0)) {
        throw new TypeError("Workspace stream must start at sequence zero");
      }
      if (snapshot.sequence >= 0 && event.type === "started") {
        throw new TypeError("Workspace stream may start only once");
      }
      if (terminalEvent) {
        throw new TypeError("Workspace stream emitted data after its terminal event");
      }

      snapshot = advanceStreamSnapshot(snapshot, event);
      if (event.type === "completed") {
        // Defer completed publication until its canonical commit has settled in queue order.
        terminalEvent = event;
        terminalSnapshot = snapshot;
        continue;
      }
      if (typeof onEvent === "function" && await onEvent(event, snapshot) === false) {
        throw new WorkspaceOperationStaleError();
      }
      if (event.type === "failed") terminalEvent = event;
    }

    if (!terminalEvent) throw new WorkspaceStreamFailedError();
    if (terminalEvent.type === "failed") {
      throw new WorkspaceStreamFailedError(terminalEvent.code, terminalEvent.recoverable);
    }
    if (signal?.aborted) throw workspaceAbortError();
    // Canonical persistence is a commit section: retain queue ownership until it settles.
    const applied = await applyResponse(latest, terminalEvent.response, operation);
    if (
      typeof onEvent === "function"
      && await onEvent(terminalEvent, terminalSnapshot) === false
    ) {
      throw new WorkspaceOperationStaleError();
    }
    return applied;
  });
}

/** Map internal failures to bounded UI-safe copy without provider, prompt, or token content. */
function safeWorkspaceErrorMessage(error) {
  if (error?.name === "WorkspaceStreamFailedError") return error.message;
  if (error?.name === "AbortError") return "Workspace request was canceled. Please retry.";
  if (error instanceof TypeError) return "Workspace response was invalid. Please retry.";
  if (Number.isInteger(error?.status)) {
    return `Workspace request failed (${error.status}). Please retry.`;
  }
  return "Workspace request failed. Please retry.";
}

/** Describe the structured UI event emitted for one Workspace operation error. */
export function workspaceOperationErrorEvent(error, tabId) {
  if (error?.name === "ExtensionUpdateRequiredError" || error?.status === 426) {
    return {
      type: "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED",
      tabId,
      updateUrl: error.updateUrl,
      requiredVersion: error.requiredVersion,
    };
  }
  const event = {
    type: "AGENT_BRIDGE_WORKSPACE_ERROR",
    tabId,
    error: safeWorkspaceErrorMessage(error),
    recoverable: error?.recoverable !== false,
  };
  if (error?.suppressBroadcast) event.stale = true;
  return event;
}
