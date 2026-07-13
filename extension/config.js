export const LOCAL_GATEWAY = "http://127.0.0.1:17321";
export const PRODUCTION_GATEWAY = "https://browser.buildwithyang.com/api";
//打包时候会把 BUILD_ENV 从 development 改成 production
export const BUILD_ENV = "development";

export function gatewayForEnvironment(env = BUILD_ENV) {
  return env === "production" ? PRODUCTION_GATEWAY : LOCAL_GATEWAY;
}

export const GATEWAY_BASE = gatewayForEnvironment();
