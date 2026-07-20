export const LOCAL_GATEWAY = "http://127.0.0.1:17321";
export const PRODUCTION_GATEWAY = "https://browser.buildwithyang.com/api";
// Wire compatibility is intentionally independent from manifest.json releases.
export const EXTENSION_PROTOCOL_VERSION = 3;
export const EXTENSION_PROTOCOL_HEADER = "X-Agent-Bridge-Protocol-Version";
export const DEFAULT_EXTENSION_UPDATE_URL =
  "https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai";
//打包时候会把 BUILD_ENV 从 development 改成 production
export const BUILD_ENV = "development";

/** Resolve the immutable Gateway base URL for one build environment. */
export function gatewayForEnvironment(env = BUILD_ENV) {
  return env === "production" ? PRODUCTION_GATEWAY : LOCAL_GATEWAY;
}

export const GATEWAY_BASE = gatewayForEnvironment();
