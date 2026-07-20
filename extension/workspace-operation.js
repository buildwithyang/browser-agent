const QUICK_INSIGHT_ACTION_IDS = new Map([
  ["analyze", "analyze"],
  ["tailor_resume", "tailor_resume"],
  ["write_cover_letter", "write_cover_letter"],
  // Accept the product-label alias while emitting the Gateway's stable Action ID.
  ["generate_cover_letter", "write_cover_letter"],
]);

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
export function createUserMessageOperation(actionId, message) {
  const userMessage = typeof message === "string" ? message.trim() : "";
  if (!userMessage) throw new TypeError("Message cannot be empty");
  return Object.freeze({
    kind: "request",
    trigger: "user_message",
    actionId: requiredActionId(actionId),
    message: userMessage,
  });
}

/** Run one request Command after reloading canonical state inside its keyed queue. */
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
    applyResponse,
  } = dependencies || {};
  if (!queue?.run || !key) throw new TypeError("Workspace operation queue and key are required");

  return queue.run(key, async () => {
    // The click-time object is intentionally ignored; queue ordering makes only this reload current.
    const latest = await loadLatest();
    const pageContext = await collectPageContext();
    const body = buildRequest(pageContext, latest, operation);
    const response = await executeRequest(body, latest, operation);
    return applyResponse(latest, response, operation);
  });
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
  return {
    type: "AGENT_BRIDGE_WORKSPACE_ERROR",
    tabId,
    error: error?.message || "Workspace request failed",
    recoverable: true,
  };
}
