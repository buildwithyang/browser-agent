import {
  WORKSPACE_SCHEMA_VERSION,
  createWorkspace,
  validatePromptShortcut,
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
const WORKSPACE_PREFILL_PREFIX = "agent-bridge:workspace-prefill";
const LEGACY_WORKSPACE_PREFIX = "agent-bridge:workspace:v2:";
const CURRENT_WORKSPACE_PREFIX = "agent-bridge:workspace:v3:";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Return one exact old-schema key that may be discarded for an owner and resource. */
function legacyWorkspaceStorageKey(ownerId, resourceUrl, schemaVersion = 2) {
  if (typeof resourceUrl !== "string" || !resourceUrl.trim()) {
    throw new TypeError("resourceUrl must be a non-empty string");
  }
  const owner = typeof ownerId === "string" && ownerId.trim() ? ownerId.trim() : "anonymous";
  const prefix = schemaVersion === 1 ? "agent-bridge:workspace:v1:" : LEGACY_WORKSPACE_PREFIX;
  return `${prefix}${encodeURIComponent(owner)}:${encodeURIComponent(
    resourceUrl.trim()
  )}`;
}

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

/** Create one mutable in-memory record for an active Workspace stream. */
export function createActiveWorkspaceStream({
  operationId,
  tabId,
  resourceUrl,
  submittedMessage = null,
  createdAt = new Date().toISOString(),
  controller,
}) {
  if (typeof operationId !== "string" || !UUID_PATTERN.test(operationId)) {
    throw new TypeError("Active Workspace operationId must be a UUID");
  }
  if (!Number.isInteger(tabId) || tabId <= 0) {
    throw new TypeError("Active Workspace tabId must be a positive integer");
  }
  if (typeof resourceUrl !== "string" || !resourceUrl) {
    throw new TypeError("Active Workspace resourceUrl is required");
  }
  if (!controller || typeof controller.abort !== "function") {
    throw new TypeError("Active Workspace AbortController is required");
  }
  return {
    generation: Symbol("workspace-stream-generation"),
    operationId,
    tabId,
    resourceUrl,
    sequence: -1,
    stage: null,
    markdown: "",
    submittedMessage: typeof submittedMessage === "string" ? submittedMessage : null,
    createdAt,
    controller,
    cancelReason: null,
  };
}

/** Accept one event only while its operation identity and sequence still own the record. */
export function acceptWorkspaceStreamEvent(active, event) {
  if (
    !active
    || !event
    || event.operation_id !== active.operationId
    || !Number.isInteger(event.sequence)
    || event.sequence <= active.sequence
  ) {
    return false;
  }
  active.sequence = event.sequence;
  if (typeof event.stage === "string" && event.stage) active.stage = event.stage;
  if (event.type === "delta") active.markdown += event.text;
  return true;
}

/** Project an active record to the public, privacy-bounded Side Panel stream contract. */
export function workspaceStreamSnapshot(active) {
  if (!active) return null;
  return {
    operationId: active.operationId,
    tabId: active.tabId,
    resourceUrl: active.resourceUrl,
    sequence: active.sequence,
    stage: active.stage,
    markdown: active.markdown,
    submittedMessage: active.submittedMessage,
    createdAt: active.createdAt,
  };
}

/** Abort one record once and retain a local lifecycle reason for stale-work suppression. */
function cancelWorkspaceStream(active, reason) {
  if (!active.cancelReason) active.cancelReason = reason;
  if (!active.controller.signal?.aborted) active.controller.abort(active.cancelReason);
}

/** Replace the stream for one owner/resource key, aborting its former operation. */
export function replaceActiveWorkspaceStream(activeStreams, key, active) {
  const previous = activeStreams.get(key);
  if (previous && previous !== active) cancelWorkspaceStream(previous, "superseded");
  activeStreams.set(key, active);
  return active;
}

/** Return whether one operation still owns its exact owner/resource registry slot. */
export function isActiveWorkspaceStream(activeStreams, key, active) {
  const current = activeStreams.get(key);
  return current === active && current?.generation === active?.generation;
}

/** Accept one event only while the supplied record owns the current internal generation. */
export function acceptActiveWorkspaceStreamEvent(activeStreams, key, active, event) {
  if (!isActiveWorkspaceStream(activeStreams, key, active)) return false;
  return acceptWorkspaceStreamEvent(active, event);
}

/** Finish only the matching registry generation so stale cleanup cannot delete its successor. */
export function finishActiveWorkspaceStream(
  activeStreams,
  key,
  expected,
  reason = "terminal"
) {
  const active = activeStreams.get(key);
  if (!isActiveWorkspaceStream(activeStreams, key, expected)) return false;
  cancelWorkspaceStream(active, reason);
  activeStreams.delete(key);
  return true;
}

/** Abort and remove every active stream selected by one tab or identity predicate. */
export function abortWorkspaceStreams(activeStreams, predicate, reason) {
  let aborted = 0;
  for (const [key, active] of activeStreams) {
    if (!predicate(active, key)) continue;
    cancelWorkspaceStream(active, reason);
    activeStreams.delete(key);
    aborted += 1;
  }
  return aborted;
}

/** Return one active stream snapshot only for its exact resource mapping and originating tab. */
export function pendingWorkspaceStream(activeStreams, key, tabId) {
  const active = activeStreams.get(key);
  if (!active || active.tabId !== tabId) return null;
  return workspaceStreamSnapshot(active);
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

/** Return the session-storage key for one tab's pending composer draft. */
export function workspacePrefillKey(tabId) {
  return `${WORKSPACE_PREFILL_PREFIX}:${tabId}`;
}

/** Persist one server-declared draft until the Side Panel ACKs its delivery token. */
export async function storeWorkspacePrefill(
  tabId,
  shortcut,
  sessionStore = chrome.storage.session
) {
  validatePromptShortcut(shortcut);
  const delivery = {
    token: crypto.randomUUID(),
    shortcut: { ...shortcut },
  };
  validateWorkspacePrefillDelivery(delivery);
  await sessionStore.set({ [workspacePrefillKey(tabId)]: delivery });
  return delivery;
}

/** Validate one tokenized prefill delivery without interpreting its prompt. */
function validateWorkspacePrefillDelivery(delivery) {
  if (!delivery || typeof delivery !== "object" || Array.isArray(delivery)) {
    throw new TypeError("Workspace prefill delivery must be an object");
  }
  const keys = Object.keys(delivery).sort();
  if (keys.length !== 2 || keys[0] !== "shortcut" || keys[1] !== "token") {
    throw new TypeError("Workspace prefill delivery must contain exactly shortcut and token");
  }
  if (typeof delivery.token !== "string" || !UUID_PATTERN.test(delivery.token)) {
    throw new TypeError("Workspace prefill delivery token must be a UUID");
  }
  validatePromptShortcut(delivery.shortcut);
  return true;
}

/** Read one pending prefill without deleting it before Side Panel acceptance. */
export async function readWorkspacePrefill(
  tabId,
  sessionStore = chrome.storage.session
) {
  const key = workspacePrefillKey(tabId);
  const values = await sessionStore.get(key);
  const delivery = values[key] ?? null;
  if (delivery === null) return null;
  try {
    validateWorkspacePrefillDelivery(delivery);
  } catch (error) {
    await sessionStore.remove(key);
    throw error;
  }
  return {
    token: delivery.token,
    shortcut: { ...delivery.shortcut },
  };
}

/** Delete a prefill only when an accepted Side Panel load ACKs its current token. */
export async function acknowledgeWorkspacePrefill(
  tabId,
  token,
  sessionStore = chrome.storage.session
) {
  if (typeof token !== "string" || !UUID_PATTERN.test(token)) {
    throw new TypeError("Workspace prefill ACK token must be a UUID");
  }
  const delivery = await readWorkspacePrefill(tabId, sessionStore);
  if (!delivery || delivery.token !== token) return false;
  await sessionStore.remove(workspacePrefillKey(tabId));
  return true;
}

/** Remove every tab-scoped Workspace mapping and saved initial selection. */
export async function clearWorkspaceSessionNamespace(sessionStore) {
  const values = await sessionStore.get(null);
  const keys = Object.keys(values || {}).filter(
    (key) => key.startsWith(`${ACTIVE_WORKSPACE_PREFIX}:`)
      || key.startsWith(`${INITIAL_SELECTION_PREFIX}:`)
      || key.startsWith(`${WORKSPACE_PREFILL_PREFIX}:`)
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

/** Validate one current v3 record against its exact owner/resource mapping. */
function validatedCurrentWorkspace(mapping, state) {
  const current = createWorkspace(state);
  if (state.schemaVersion !== WORKSPACE_SCHEMA_VERSION) throw new TypeError("schema");
  if (current.resourceUrl !== mapping.resourceUrl) throw new TypeError("resource");
  validateWorkspaceState(current.histories, current.artifacts);
  return current;
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
  if (
    typeof mapping.storageKey !== "string"
    || !mapping.storageKey.startsWith(CURRENT_WORKSPACE_PREFIX)
  ) {
    let isExactLegacyKey = false;
    try {
      isExactLegacyKey = [1, 2].some(
        (version) => mapping.storageKey === legacyWorkspaceStorageKey(
          ownerId,
          mapping.resourceUrl,
          version
        )
      );
    } catch {
      // Invalid mapping metadata is discarded without touching local Workspace records.
    }
    const cleanup = [sessionStore.remove(mappingKey)];
    if (isExactLegacyKey) cleanup.push(workspaceStore.remove(mapping.storageKey));
    await Promise.all(cleanup);
    return null;
  }
  let currentStorageKey = null;
  try {
    currentStorageKey = workspaceStorageKey(ownerId, mapping.resourceUrl);
  } catch {
    // The invalid mapping is discarded below without reading arbitrary local state.
  }
  if (mapping.storageKey !== currentStorageKey) {
    await sessionStore.remove(mappingKey);
    return null;
  }
  const stored = await workspaceStore.get(currentStorageKey);
  const state = stored[currentStorageKey];
  if (!state) return null;
  try {
    const current = validatedCurrentWorkspace(mapping, state);
    return { mapping, state: current, lang: mapping.lang || "en" };
  } catch {
    await Promise.all([
      sessionStore.remove(mappingKey),
      workspaceStore.remove(currentStorageKey),
    ]);
    return null;
  }
}

/** Load exact v3 seed state or discard the exact owner/resource v2 record. */
export async function loadWorkspaceForSeed(
  _tabId,
  { ownerId, resourceUrl, lang = "en", workspaceStore }
) {
  const currentStorageKey = workspaceStorageKey(ownerId, resourceUrl);
  const currentData = await workspaceStore.get(currentStorageKey);
  const currentState = currentData[currentStorageKey];
  if (currentState !== undefined) {
    const mapping = {
      ownerId,
      storageKey: currentStorageKey,
      resourceUrl,
      lang,
    };
    try {
      return {
        mapping,
        state: validatedCurrentWorkspace(mapping, currentState),
        lang,
      };
    } catch {
      await workspaceStore.remove(currentStorageKey);
    }
  }

  const legacyStorageKeys = [1, 2].map(
    (version) => legacyWorkspaceStorageKey(ownerId, resourceUrl, version)
  );
  const legacyData = await workspaceStore.get(legacyStorageKeys);
  const presentLegacyKeys = legacyStorageKeys.filter(
    (storageKey) => legacyData[storageKey] !== undefined
  );
  if (presentLegacyKeys.length) {
    await workspaceStore.remove(presentLegacyKeys);
  }
  return null;
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
  const shortcuts = Array.isArray(seed.shortcuts) ? seed.shortcuts : [];

  return createWorkspace({
    resourceUrl: seed.resourceUrl || current.resourceUrl,
    pageTitle: typeof seed.pageTitle === "string" ? seed.pageTitle : current.pageTitle,
    quickInsight: seed.quickInsight ?? current.quickInsight,
    shortcuts,
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

/** Validate the Gateway protocol Header before any status, auth, or body handling. */
export function assertGatewayProtocolResponse(response) {
  const protocolHeader = response?.headers?.get?.(EXTENSION_PROTOCOL_HEADER) ?? null;
  if (protocolHeader !== String(EXTENSION_PROTOCOL_VERSION)) {
    throw extensionUpdateError(null, protocolHeader);
  }
  return protocolHeader;
}

/** Validate one successful body protocol using the existing Extension update semantics. */
export function assertGatewayBodyProtocol(
  body,
  protocolHeader = String(EXTENSION_PROTOCOL_VERSION)
) {
  if (body?.protocol_version !== EXTENSION_PROTOCOL_VERSION) {
    throw extensionUpdateError(body, protocolHeader);
  }
}

/** Validate protocol compatibility before converting HTTP status or JSON failures. */
export async function readGatewayResponse(response) {
  // Header inspection is deliberately first so a version mismatch can never become a 401 clear.
  const protocolHeader = assertGatewayProtocolResponse(response);
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
  assertGatewayBodyProtocol(body, protocolHeader);
  return body;
}
