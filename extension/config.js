export const LOCAL_GATEWAY = "http://127.0.0.1:17321";
export const PRODUCTION_GATEWAY = "https://browser.buildwithyang.com/api";
export const BUILD_ENV = "development";

export function gatewayForEnvironment(env = BUILD_ENV) {
  return env === "production" ? PRODUCTION_GATEWAY : LOCAL_GATEWAY;
}

export const GATEWAY_BASE = gatewayForEnvironment();
