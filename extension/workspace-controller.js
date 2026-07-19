import { createWorkspace } from "./workspace.js";

const ACTIVE_WORKSPACE_PREFIX = "agent-bridge:active-workspace:v1";
const INITIAL_SELECTION_PREFIX = "agent-bridge:initial-selection:v1";

/** Error raised when the gateway returns a syntactically valid non-success response. */
export class GatewayHttpError extends Error {
  /** Preserve the HTTP status for authentication and retry policy. */
  constructor(status, message) {
    super(message || `Gateway request failed (${status})`);
    this.name = "GatewayHttpError";
    this.status = status;
  }
}

/** Return the session-storage key that maps one tab to its active local Workspace. */
export function activeWorkspaceKey(tabId) {
  return `${ACTIVE_WORKSPACE_PREFIX}:${tabId}`;
}

/** Return the session-storage key for one tab's URL-bound initial selection. */
export function initialSelectionKey(tabId) {
  return `${INITIAL_SELECTION_PREFIX}:${tabId}`;
}

/** Remove every tab-scoped Workspace mapping and saved initial selection. */
export async function clearWorkspaceSessionNamespace(sessionStore) {
  const values = await sessionStore.get(null);
  const keys = Object.keys(values || {}).filter(
    (key) => key.startsWith(`${ACTIVE_WORKSPACE_PREFIX}:`)
      || key.startsWith(`${INITIAL_SELECTION_PREFIX}:`)
  );
  if (keys.length) await sessionStore.remove(keys);
}

/** Clear authentication and all identity-bound session state while preserving local records. */
export async function clearAuthWorkspaceState({ localStore, sessionStore, authKeys }) {
  await Promise.all([
    localStore.remove(authKeys),
    clearWorkspaceSessionNamespace(sessionStore),
  ]);
}

/** Load a tab Workspace only when its mapping belongs to the current stable owner. */
export async function loadOwnerScopedWorkspace(
  tabId,
  { ownerId, sessionStore, workspaceStore }
) {
  const mappingKey = activeWorkspaceKey(tabId);
  const mappingData = await sessionStore.get(mappingKey);
  const mapping = mappingData[mappingKey];
  if (!mapping?.storageKey) return null;
  if (mapping.ownerId !== ownerId) {
    await sessionStore.remove(mappingKey);
    return null;
  }
  const stored = await workspaceStore.get(mapping.storageKey);
  const state = stored[mapping.storageKey];
  return state ? { mapping, state, lang: mapping.lang || "en" } : null;
}

/** Create an operation queue that serializes work per key without coupling other keys. */
export function createKeyedQueue() {
  const pendingByKey = new Map();
  return {
    /** Enqueue one operation after the latest operation for the same key. */
    run(key, operation) {
      const previous = pendingByKey.get(key);
      const current = previous
        ? previous.catch(() => undefined).then(operation)
        : Promise.resolve().then(operation);
      pendingByKey.set(key, current);
      return current.finally(() => {
        if (pendingByKey.get(key) === current) pendingByKey.delete(key);
      });
    },
    /** Return the latest pending operation for one key, if any. */
    pending(key) {
      return pendingByKey.get(key);
    },
  };
}

/** Reload canonical state inside a keyed critical section before applying an operation. */
export function enqueueLatestByKey(queue, key, loadLatest, operation) {
  return queue.run(key, async () => operation(await loadLatest()));
}

/** Serialize a Side Panel GET behind the user-gesture seed that opened the panel. */
export async function loadAfterPendingSeed(pendingSeed, loadWorkspace) {
  if (pendingSeed) await pendingSeed;
  return loadWorkspace();
}

/** Refresh Quick Insight metadata without discarding a Workspace conversation or artifact. */
export function mergeWorkspaceSeed(existing, seed = {}) {
  const current = createWorkspace(existing || {});
  const actions = Array.isArray(seed.actions) ? seed.actions : [];
  const actionIds = new Set(actions.map((action) => action?.id).filter(Boolean));
  const priorSelectedActionId = existing?.selectedActionId || current.selectedActionId;
  const selectedActionId = actionIds.has(seed.actionId)
    ? seed.actionId
    : actionIds.has(priorSelectedActionId)
      ? priorSelectedActionId
      : seed.defaultActionId;

  return createWorkspace({
    resourceUrl: seed.resourceUrl || current.resourceUrl,
    pageTitle: typeof seed.pageTitle === "string" ? seed.pageTitle : current.pageTitle,
    quickInsight: seed.quickInsight ?? current.quickInsight,
    actions,
    selectedActionId,
    defaultActionId: seed.defaultActionId,
    histories: current.histories,
    currentDocument: current.currentDocument,
    updatedAt: current.updatedAt,
  });
}

/** Restore the initial job description only when fresh selection is empty on the same URL. */
export function restoreInitialSelection(pageContext, initialSelection) {
  const fresh = { ...(pageContext || {}) };
  const saved = initialSelection && typeof initialSelection === "object"
    ? initialSelection
    : {};
  if (
    !fresh.selectedText
    && fresh.url
    && fresh.url === saved.url
    && typeof saved.selectedText === "string"
  ) {
    fresh.selectedText = saved.selectedText;
  }
  return fresh;
}

/** Parse a gateway response and reject every non-2xx status with a useful detail. */
export async function readGatewayResponse(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = typeof body?.detail === "string"
      ? body.detail
      : typeof body?.message === "string"
        ? body.message
        : `Gateway request failed (${response.status})`;
    throw new GatewayHttpError(response.status, detail);
  }
  return body;
}
