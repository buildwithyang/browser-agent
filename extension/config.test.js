import { test } from "node:test";
import assert from "node:assert/strict";

import { LOCAL_GATEWAY, PRODUCTION_GATEWAY, gatewayForEnvironment } from "./config.js";

test("source build defaults to local gateway", () => {
  assert.equal(gatewayForEnvironment(undefined), LOCAL_GATEWAY);
});

test("production environment selects cloud gateway", () => {
  assert.equal(gatewayForEnvironment("production"), PRODUCTION_GATEWAY);
});
