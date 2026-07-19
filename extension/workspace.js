/** The explicit owner used by self-hosted extensions without authentication. */
export const ANONYMOUS_WORKSPACE_OWNER = "anonymous";

const WORKSPACE_STORAGE_PREFIX = "agent-bridge:workspace:v1";
const USER_HISTORY_CONTENT_MAX_CHARS = 10_000;
const ASSISTANT_HISTORY_CONTENT_MAX_CHARS = 100_000;

/** Return a stable owner id without deriving identity from a bearer token. */
function normalizedOwnerId(ownerId) {
  return typeof ownerId === "string" && ownerId.trim()
    ? ownerId.trim()
    : ANONYMOUS_WORKSPACE_OWNER;
}

/** Return only the valid action ids from a backend-declared Action collection. */
function actionIds(actions) {
  if (!Array.isArray(actions)) return [];
  return actions
    .map((action) => (action && typeof action.id === "string" ? action.id : null))
    .filter(Boolean);
}

/** Select a valid Action, preferring an existing choice over the backend default. */
function selectActionId(actions, selectedActionId, defaultActionId) {
  const ids = actionIds(actions);
  if (ids.includes(selectedActionId)) return selectedActionId;
  if (ids.includes(defaultActionId)) return defaultActionId;
  return ids[0] || null;
}

/** Return an owner- and resource-scoped, versioned chrome.storage.local key. */
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

/** Create the privacy-bounded local Workspace state stored by the extension. */
export function createWorkspace(seed = {}) {
  const actions = Array.isArray(seed.actions) ? [...seed.actions] : [];
  return {
    resourceUrl: typeof seed.resourceUrl === "string" ? seed.resourceUrl : "",
    pageTitle: typeof seed.pageTitle === "string" ? seed.pageTitle : "",
    quickInsight: seed.quickInsight ?? null,
    actions,
    selectedActionId: selectActionId(
      actions,
      seed.selectedActionId,
      seed.defaultActionId ?? seed.default_action_id
    ),
    histories: Array.isArray(seed.histories) ? [...seed.histories] : [],
    currentDocument: seed.currentDocument ?? null,
    updatedAt: seed.updatedAt ?? null,
  };
}

/** Replace canonical Workspace fields with one complete gateway response. */
export function applyWorkspaceResponse(state, response) {
  const current = createWorkspace(state);
  const incoming = response && typeof response === "object" ? response : {};
  const incomingResourceUrl = incoming.resourceUrl ?? incoming.resource_url;
  const incomingSelectedActionId = incoming.selectedActionId ?? incoming.selected_action_id;
  const resourceUrl =
    typeof incomingResourceUrl === "string" && incomingResourceUrl.trim()
      ? incomingResourceUrl
      : current.resourceUrl;
  return {
    ...current,
    resourceUrl,
    selectedActionId: selectActionId(
      current.actions,
      incomingSelectedActionId,
      current.selectedActionId
    ),
    histories: Array.isArray(incoming.histories) ? [...incoming.histories] : [],
    currentDocument: incoming.document ?? null,
    updatedAt: incoming.updatedAt ?? incoming.meta?.created_at ?? null,
  };
}

/** Return whether one local entry satisfies the gateway HistoryMessage input contract. */
function isValidHistoryMessage(message) {
  if (!message || typeof message !== "object" || Array.isArray(message)) return false;
  if (message.role !== "user" && message.role !== "assistant") return false;
  if (typeof message.content !== "string") return false;
  if (message.role === "user") {
    return message.content.length >= 1 && message.content.length <= USER_HISTORY_CONTENT_MAX_CHARS;
  }
  return message.content.length <= ASSISTANT_HISTORY_CONTENT_MAX_CHARS;
}

/** Return whether the next user message fits the ten-message request contract. */
export function canSend(state) {
  if (!state || !Array.isArray(state.histories)) return false;
  if (state.histories.length + 1 > 10) return false;
  // Array.prototype.every skips holes, so validate by index instead.
  for (let index = 0; index < state.histories.length; index += 1) {
    if (!(index in state.histories) || !isValidHistoryMessage(state.histories[index])) {
      return false;
    }
  }
  return true;
}
