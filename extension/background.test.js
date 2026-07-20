import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import * as auth from "./auth.js";
import { applyWorkspaceResponse, createWorkspace } from "./workspace.js";

const RESOURCE_URL = "https://example.com/jobs/1";
const ARTIFACT_ID = "10000000-0000-4000-8000-000000000001";
const ATTACHMENT_ID = "20000000-0000-4000-8000-000000000001";

/** Build a complete successful first Artifact response from the Gateway. */
function firstArtifactResponse() {
  const attachment = {
    id: ATTACHMENT_ID,
    artifact_id: ARTIFACT_ID,
    version: 1,
    type: "cover_letter",
    title: "Cover Letter",
    content: "Dear Hiring Manager",
  };
  return {
    resource_url: RESOURCE_URL,
    selected_action_id: "write_cover_letter",
    result_type: "create_artifact",
    histories: [{
      id: "30000000-0000-4000-8000-000000000001",
      role: "assistant",
      content: "Created the first draft.",
      action_id: "write_cover_letter",
      created_at: "2026-07-20T10:00:00Z",
      attachments: [attachment],
    }],
    artifacts: {
      cv: null,
      cover_letter: {
        id: ARTIFACT_ID,
        type: "cover_letter",
        version: 1,
        title: "Cover Letter",
        draft: "Dear Hiring Manager",
        attachment,
      },
    },
    meta: {
      id: "40000000-0000-4000-8000-000000000001",
      created_at: "2026-07-20T10:00:00Z",
      status: "completed",
      input_chars: 123,
      model: "test-model",
      started_at: "2026-07-20T09:59:59Z",
      finished_at: "2026-07-20T10:00:00Z",
      duration_ms: 1000,
    },
    protocol_version: 2,
  };
}

test("next SEND carries the complete Artifact state returned by the prior response", async () => {
  assert.equal(
    typeof auth.buildUserMessageWorkspaceBody,
    "function",
    "background must share a pure v2 SEND builder"
  );
  const state = applyWorkspaceResponse(
    createWorkspace({
      resourceUrl: RESOURCE_URL,
      actions: [{ id: "write_cover_letter", title: "Write cover letter" }],
      selectedActionId: "write_cover_letter",
    }),
    firstArtifactResponse()
  );

  const body = auth.buildUserMessageWorkspaceBody(
    { url: RESOURCE_URL, title: "Job", selectedText: "JD" },
    {
      resourceUrl: RESOURCE_URL,
      actionId: "write_cover_letter",
      state,
      message: "Make it shorter",
      lang: "en",
    }
  );

  assert.equal(body.trigger, "user_message");
  assert.deepEqual(body.histories, state.histories);
  assert.deepEqual(body.artifacts, state.artifacts);
  assert.deepEqual(
    body.histories[0].attachments[0],
    body.artifacts.cover_letter.attachment
  );
  assert.equal("currentDocument" in body, false);

  const source = await readFile(new URL("./background.js", import.meta.url), "utf8");
  const sendFunction = source.slice(
    source.indexOf("async function sendWorkspaceTurn"),
    source.indexOf("function notifyWorkspaceUpdated")
  );
  assert.match(sendFunction, /buildUserMessageWorkspaceBody/);
  assert.doesNotMatch(sendFunction, /currentDocument/);
});
