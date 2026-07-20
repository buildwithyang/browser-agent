import {
  WORKSPACE_SCHEMA_VERSION,
  createWorkspace,
  legacyWorkspaceStorageKey,
  migrateWorkspaceV1,
  validateWorkspaceState,
  workspaceStorageKey,
} from "./workspace.js";
import {
  DEFAULT_EXTENSION_UPDATE_URL,
  EXTENSION_PROTOCOL_HEADER,
  EXTENSION_PROTOCOL_VERSION,
} from "./config.js";

const ACTIVE_WORKSPACE_PREFIX = "agent-bridge:active-workspace:v1";
const INITIAL_SELECTION_PREFIX = "agent-bridge:initial-selection:v1";
const LEGACY_WORKSPACE_PREFIX = "agent-bridge:workspace:v1:";

/** Error raised when the gateway returns a syntactically valid non-success response. */
export class GatewayHttpError extends Error {
  /** Preserve the HTTP status for authentication and retry policy. */
  constructor(status, message) {
    super(message || `Gateway request failed (${status})`);
    this.name = "GatewayHttpError";
    this.status = status;
  }
}

/** Error raised before auth/business handling when Gateway wire versions are incompatible. */
export class ExtensionUpdateRequiredError extends Error {
  /** Preserve the required protocol and best available Extension update destination. */
  constructor({
    requiredVersion = EXTENSION_PROTOCOL_VERSION,
    updateUrl = DEFAULT_EXTENSION_UPDATE_URL,
    message = "Extension update required",
  } = {}) {
    super(message);
    this.name = "ExtensionUpdateRequiredError";
    this.status = 426;
    this.requiredVersion = requiredVersion;
    this.updateUrl = updateUrl;
  }
}

/** Error raised when a request crosses an authentication identity boundary. */
export class AuthSnapshotChangedError extends Error {
  /** Create a stable error type for silent stale-operation cancellation. */
  constructor() {
    super("Authentication changed while the Workspace operation was running");
    this.name = "AuthSnapshotChangedError";
  }
}

/** Create one immutable token-and-owner identity snapshot. */
export function createAuthSnapshot(token, ownerId) {
  return Object.freeze({
    token: typeof token === "string" ? token : "",
    ownerId: typeof ownerId === "string" && ownerId.trim()
      ? ownerId.trim()
      : "anonymous",
  });
}

/** Return whether two authentication snapshots represent exactly one credential generation. */
export function authSnapshotsEqual(left, right) {
  return !!left
    && !!right
    && left.token === right.token
    && left.ownerId === right.ownerId;
}

/** Apply a completed response only while its request owner is still current. */
export async function applyForCurrentOwner({
  snapshot,
  readCurrentSnapshot,
  apply,
  onOwnerMismatch,
}) {
  const current = await readCurrentSnapshot();
  if (snapshot.ownerId !== current.ownerId) {
    if (typeof onOwnerMismatch === "function") await onOwnerMismatch();
    throw new AuthSnapshotChangedError();
  }
  return apply();
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

/** Clear auth and Workspace sessions only if a failed request still owns current credentials. */
export async function clearAuthWorkspaceStateIfCurrent({
  snapshot,
  readCurrentSnapshot,
  localStore,
  sessionStore,
  authKeys,
  onCleared,
}) {
  if (!authSnapshotsEqual(snapshot, await readCurrentSnapshot())) return false;
  await clearAuthWorkspaceState({ localStore, sessionStore, authKeys });
  if (typeof onCleared === "function") await onCleared();
  return true;
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
  const pointsToLegacy = mapping.storageKey.startsWith(LEGACY_WORKSPACE_PREFIX);
  if (pointsToLegacy) {
    let expectedLegacyKey = null;
    try {
      expectedLegacyKey = legacyWorkspaceStorageKey(ownerId, mapping.resourceUrl);
    } catch {
      return null;
    }
    if (mapping.storageKey !== expectedLegacyKey) return null;
  }
  const stored = await workspaceStore.get(mapping.storageKey);
  const state = stored[mapping.storageKey];
  if (!state) return null;
  if (!pointsToLegacy) {
    return { mapping, state, lang: mapping.lang || "en" };
  }
  return migrateOwnerScopedWorkspace({
    mappingKey,
    mapping,
    state,
    sessionStore,
    workspaceStore,
  });
}

/** Safely migrate an active v1 record before removing its only recoverable copy. */
async function migrateOwnerScopedWorkspace({
  mappingKey,
  mapping,
  state,
  sessionStore,
  workspaceStore,
}) {
  const resourceUrl = mapping.resourceUrl || state.resourceUrl;
  const nextState = migrateWorkspaceV1({ ...state, resourceUrl });
  const nextStorageKey = workspaceStorageKey(mapping.ownerId, resourceUrl);
  const nextMapping = {
    ...mapping,
    storageKey: nextStorageKey,
    resourceUrl,
  };
  let mappingWriteAttempted = false;

  try {
    // Keep v1 intact until v2 has survived both Chrome serialization and a fresh read.
    await workspaceStore.set({ [nextStorageKey]: nextState });
    const confirmedData = await workspaceStore.get(nextStorageKey);
    const confirmed = confirmedData[nextStorageKey];
    if (!confirmed || confirmed.schemaVersion !== WORKSPACE_SCHEMA_VERSION) {
      throw new Error("Workspace v2 migration verification failed");
    }
    validateWorkspaceState(confirmed.histories, confirmed.artifacts);

    mappingWriteAttempted = true;
    await sessionStore.set({ [mappingKey]: nextMapping });
    await workspaceStore.remove(mapping.storageKey);
    return { mapping: nextMapping, state: confirmed, lang: mapping.lang || "en" };
  } catch (error) {
    // If the mapping write or final removal fails, restore the old active pointer.
    if (mappingWriteAttempted) {
      try {
        await sessionStore.set({ [mappingKey]: mapping });
      } catch (rollbackError) {
        throw new AggregateError(
          [error, rollbackError],
          "Workspace migration failed and mapping rollback failed"
        );
      }
    }
    throw error;
  }
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

/** Refresh Quick Insight metadata without discarding a Workspace conversation or Artifacts. */
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
    artifacts: current.artifacts,
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

/** Select a positive integer protocol requirement from direct 426 metadata or Header text. */
function requiredProtocolVersion(body, headerValue) {
  const direct = body?.required_protocol_version;
  if (Number.isInteger(direct) && direct > 0) return direct;
  if (/^[1-9]\d*$/.test(headerValue || "")) return Number(headerValue);
  return EXTENSION_PROTOCOL_VERSION;
}

/** Build one protocol error using direct Gateway metadata with local fallbacks. */
function extensionUpdateError(body, headerValue) {
  return new ExtensionUpdateRequiredError({
    requiredVersion: requiredProtocolVersion(body, headerValue),
    updateUrl: typeof body?.update_url === "string" && body.update_url.trim()
      ? body.update_url
      : DEFAULT_EXTENSION_UPDATE_URL,
    message: typeof body?.message === "string" && body.message
      ? body.message
      : "Extension update required",
  });
}

/** Validate protocol compatibility before converting HTTP status or JSON failures. */
export async function readGatewayResponse(response) {
  // Header inspection is deliberately first so a version mismatch can never become a 401 clear.
  const protocolHeader = response?.headers?.get?.(EXTENSION_PROTOCOL_HEADER) ?? null;
  if (protocolHeader !== String(EXTENSION_PROTOCOL_VERSION)) {
    throw extensionUpdateError(null, protocolHeader);
  }
  let body = null;
  let parseFailed = false;
  try {
    body = await response.json();
  } catch {
    parseFailed = true;
  }
  if (response.status === 426) {
    throw extensionUpdateError(body, protocolHeader);
  }
  if (!response.ok) {
    const detail = typeof body?.detail === "string"
      ? body.detail
      : typeof body?.message === "string"
        ? body.message
        : `Gateway request failed (${response.status})`;
    throw new GatewayHttpError(response.status, detail);
  }
  if (
    parseFailed
    || !body
    || typeof body !== "object"
    || Array.isArray(body)
  ) {
    throw new TypeError("Gateway returned no valid JSON object");
  }
  if (body.protocol_version !== EXTENSION_PROTOCOL_VERSION) {
    throw extensionUpdateError(body, protocolHeader);
  }
  return body;
}
