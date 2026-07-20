import { test } from "node:test";
import assert from "node:assert/strict";

import {
  readWorkspaceEventStream,
  validateWorkspaceStreamEvent,
} from "./workspace-stream.js";
import { ExtensionUpdateRequiredError, GatewayHttpError } from "./workspace-controller.js";
import { DEFAULT_EXTENSION_UPDATE_URL } from "./config.js";

const OPERATION_ID = "00000000-0000-0000-0000-000000000001";
const encoder = new TextEncoder();

/** Build one valid protocol-v3 Workspace response for completed-event validation. */
function workspaceResponse(overrides = {}) {
  return {
    resource_url: "https://example.com/article",
    selected_action_id: "ask_more",
    result_type: "reply",
    histories: [],
    artifacts: { cv: null, cover_letter: null },
    meta: {
      id: "00000000-0000-0000-0000-000000000002",
      created_at: "2026-07-20T12:00:00Z",
      status: "completed",
      input_chars: 12,
      model: "test-model",
      started_at: "2026-07-20T12:00:00Z",
      finished_at: "2026-07-20T12:00:01Z",
      duration_ms: 1000,
    },
    protocol_version: 3,
    ...overrides,
  };
}

/** Build a started event with a configurable sequence and operation identity. */
function started(sequence = 0, operationId = OPERATION_ID) {
  return {
    type: "started",
    operation_id: operationId,
    sequence,
    created_at: "2026-07-20T12:00:00Z",
  };
}

/** Build a failed terminal event with a configurable sequence and operation identity. */
function failed(sequence, operationId = OPERATION_ID) {
  return {
    type: "failed",
    operation_id: operationId,
    sequence,
    code: "model_error",
    message: "Workspace generation failed",
    recoverable: true,
  };
}

/** Encode event objects as one complete NDJSON byte sequence. */
function encodeEvents(events, { finalNewline = true, lineEnding = "\n" } = {}) {
  const text = events.map((event) => JSON.stringify(event)).join(lineEnding);
  return encoder.encode(finalNewline ? `${text}${lineEnding}` : text);
}

/** Build a Fetch Response whose body exposes the supplied byte chunks in order. */
function streamResponse(
  chunks,
  {
    status = 200,
    protocol = "3",
    contentType = "application/x-ndjson; charset=utf-8",
  } = {}
) {
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
  return new Response(body, {
    status,
    headers: {
      "Content-Type": contentType,
      "X-Agent-Bridge-Protocol-Version": protocol,
    },
  });
}

/** Consume one Workspace event stream into an array for assertions. */
async function collect(response) {
  const events = [];
  for await (const event of readWorkspaceEventStream(response)) events.push(event);
  return events;
}

test("NDJSON parser preserves a Chinese code point split across byte chunks", async () => {
  const encoded = encodeEvents([
    started(),
    { type: "delta", operation_id: OPERATION_ID, sequence: 1, text: "岗" },
    failed(2),
  ]);
  const chineseByte = encoded.indexOf(0xe5);
  const events = await collect(streamResponse([
    encoded.slice(0, chineseByte + 1),
    encoded.slice(chineseByte + 1),
  ]));

  assert.equal(events[1].text, "岗");
});

test("NDJSON parser handles multiple lines and one line split across chunks", async () => {
  const encoded = encodeEvents([
    started(),
    { type: "status", operation_id: OPERATION_ID, sequence: 1, stage: "routing" },
    failed(2),
  ]);
  const split = encoded.indexOf(encoder.encode('"routing"')[0]) + 3;
  const events = await collect(streamResponse([
    encoded.slice(0, split),
    encoded.slice(split),
  ]));

  assert.deepEqual(events.map((event) => event.type), ["started", "status", "failed"]);
});

test("NDJSON parser validates a completed response through the canonical Workspace boundary", async () => {
  const events = await collect(streamResponse([encodeEvents([
    started(),
    {
      type: "completed",
      operation_id: OPERATION_ID,
      sequence: 1,
      response: workspaceResponse(),
    },
  ], { finalNewline: false })]));

  assert.equal(events[1].response.protocol_version, 3);

  await assert.rejects(
    collect(streamResponse([encodeEvents([
      started(),
      {
        type: "completed",
        operation_id: OPERATION_ID,
        sequence: 1,
        response: workspaceResponse({ protocol_version: 2 }),
      },
    ])])),
    (error) => error instanceof ExtensionUpdateRequiredError
      && error.status === 426
      && error.requiredVersion === 3
      && error.updateUrl === DEFAULT_EXTENSION_UPDATE_URL
  );
});

test("NDJSON parser accepts legal CRLF framing", async () => {
  const events = await collect(streamResponse([encodeEvents(
    [started(), failed(1)],
    { lineEnding: "\r\n" }
  )]));

  assert.deepEqual(events.map((event) => event.type), ["started", "failed"]);
});

test("stream events reject unknown keys and invalid discriminator-specific fields", () => {
  assert.throws(
    () => validateWorkspaceStreamEvent({ ...started(), unexpected: true }),
    /exactly/i
  );
  assert.throws(
    () => validateWorkspaceStreamEvent({
      type: "status",
      operation_id: OPERATION_ID,
      sequence: 1,
      stage: "routing",
      artifact_type: "cv",
    }),
    /artifact/i
  );
  assert.equal(validateWorkspaceStreamEvent({
    type: "status",
    operation_id: OPERATION_ID,
    sequence: 1,
    stage: "routing",
    artifact_type: null,
  }).artifact_type, null);
  assert.throws(
    () => validateWorkspaceStreamEvent({
      type: "status",
      operation_id: OPERATION_ID,
      sequence: 1,
      stage: "generating_artifact",
    }),
    /artifact/i
  );
  assert.equal(validateWorkspaceStreamEvent({
    type: "status",
    operation_id: OPERATION_ID,
    sequence: 1,
    stage: "generating_artifact",
    artifact_type: "cover_letter",
  }).artifact_type, "cover_letter");
  assert.throws(
    () => validateWorkspaceStreamEvent({ ...failed(1), code: "secret_provider_error" }),
    /code/i
  );
});

test("Workspace stream requires a Fetch ReadableStream body before yielding events", async () => {
  for (const body of [null, {}]) {
    const seen = [];
    const response = {
      ok: true,
      headers: {
        get(name) {
          return name.toLowerCase() === "content-type"
            ? "application/x-ndjson; charset=utf-8"
            : "3";
        },
      },
      body,
    };

    await assert.rejects(async () => {
      for await (const event of readWorkspaceEventStream(response)) seen.push(event.type);
    }, (error) => error instanceof TypeError && /ReadableStream/i.test(error.message));
    assert.deepEqual(seen, []);
  }
});

test("stream events require canonical UUIDs and non-negative integer sequences", () => {
  assert.throws(
    () => validateWorkspaceStreamEvent({ ...started(), operation_id: "not-a-uuid" }),
    /operation_id/i
  );
  for (const sequence of [-1, 1.5]) {
    assert.throws(
      () => validateWorkspaceStreamEvent({ ...started(sequence) }),
      /sequence/i
    );
  }
});

test("Workspace stream requires started first at sequence zero", async () => {
  await assert.rejects(
    collect(streamResponse([encodeEvents([
      { type: "delta", operation_id: OPERATION_ID, sequence: 0, text: "early" },
      failed(1),
    ])])),
    /started.*first/i
  );
  await assert.rejects(
    collect(streamResponse([encodeEvents([started(1), failed(2)])])),
    /sequence.*zero/i
  );
});

test("Workspace stream requires one operation identity and strictly increasing sequences", async () => {
  await assert.rejects(
    collect(streamResponse([encodeEvents([
      started(),
      { type: "delta", operation_id: "00000000-0000-0000-0000-000000000002", sequence: 1, text: "wrong" },
      failed(2),
    ])])),
    /operation_id/i
  );
  await assert.rejects(
    collect(streamResponse([encodeEvents([
      started(),
      { type: "delta", operation_id: OPERATION_ID, sequence: 0, text: "duplicate" },
      failed(1),
    ])])),
    /sequence/i
  );
});

test("Workspace stream rejects duplicate terminals and events after a terminal", async () => {
  await assert.rejects(
    collect(streamResponse([encodeEvents([started(), failed(1), failed(2)])])),
    /terminal/i
  );
});

test("Workspace stream rejects invalid trailing JSON and a missing terminal", async () => {
  const prefix = encodeEvents([started()], { finalNewline: true });
  const invalid = encoder.encode('{"type":"delta"');
  const bytes = new Uint8Array(prefix.length + invalid.length);
  bytes.set(prefix);
  bytes.set(invalid, prefix.length);

  await assert.rejects(collect(streamResponse([bytes])), /JSON|NDJSON/i);
  await assert.rejects(
    collect(streamResponse([encodeEvents([started()])])),
    /one terminal event/i
  );
});

test("trailing corruption never exposes a completed event as success", async () => {
  const prefix = encodeEvents([
    started(),
    {
      type: "completed",
      operation_id: OPERATION_ID,
      sequence: 1,
      response: workspaceResponse(),
    },
  ]);
  const invalid = encoder.encode('{"type":"delta"');
  const bytes = new Uint8Array(prefix.length + invalid.length);
  bytes.set(prefix);
  bytes.set(invalid, prefix.length);
  const seen = [];

  await assert.rejects(async () => {
    for await (const event of readWorkspaceEventStream(streamResponse([bytes]))) {
      seen.push(event.type);
    }
  }, /JSON|NDJSON/i);
  assert.deepEqual(seen, ["started"]);
});

test("Workspace stream validates protocol Header before HTTP status and media type", async () => {
  await assert.rejects(
    collect(streamResponse([encoder.encode('{"detail":"expired"}')], {
      status: 401,
      protocol: "2",
      contentType: "application/json",
    })),
    (error) => error instanceof ExtensionUpdateRequiredError && error.status === 426
  );
  await assert.rejects(
    collect(streamResponse([encoder.encode('{"detail":"expired"}')], {
      status: 401,
      contentType: "application/json",
    })),
    (error) => error instanceof GatewayHttpError
      && error.status === 401
      && error.message === "expired"
  );
  await assert.rejects(
    collect(streamResponse([encodeEvents([started(), failed(1)])], {
      contentType: "application/json",
    })),
    /content-type|NDJSON/i
  );
});
