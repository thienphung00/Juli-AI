import { readFileSync } from "node:fs";
import { join } from "node:path";

import * as contracts from "@juli/contracts";
import { GOLDEN_AGENT_EVENTS } from "@juli/contracts";
import { describe, expect, it, vi } from "vitest";

import {
  AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS,
  AgentEventStreamClient,
  AgentEventStreamHttpError,
  AgentEventStreamNetworkError,
  AgentEventParseError,
  buildAgentEventStreamHeaders,
  buildAgentEventStreamUrl,
  extractSseFrames,
  isTerminalAgentEvent,
  openAgentEventStream,
  parseSseFrame,
  type AgentEventStreamCloseReason,
  type AgentEventStreamError,
  type AgentEventStreamHandlers,
} from "../agent-event-stream";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const TOKEN = "top-secret-bearer-token";

function payloadFor(eventType: string): Record<string, unknown> {
  switch (eventType) {
    case "workflow.started":
      return { workflow_key: "optimize_product", product_ref: "prod-1", prompt_version: "v1" };
    case "workflow.status":
      return { phase_narration: "Đang xử lý..." };
    case "assistant.text":
      return { text: "hello" };
    case "tool.started":
      return { tool_call_id: "call_1", tool_name: "update_price" };
    case "tool.completed":
      return { tool_call_id: "call_1", tool_name: "update_price", ok: true, summary: "done" };
    case "workflow.completed":
      return { stop_reason: "final_response" };
    case "workflow.failed":
      return { status: "failed", stop_reason: "llm_error" };
    default:
      return {};
  }
}

function makeFrame(seq: number, eventType: string, payloadOverride?: Record<string, unknown>): string {
  const envelope = {
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type: eventType,
    timestamp: `2026-08-14T12:00:${String(seq).padStart(2, "0")}Z`,
    payload: payloadOverride ?? payloadFor(eventType),
    v: 1,
  };
  return `id: ${seq}\nevent: ${eventType}\ndata: ${JSON.stringify(envelope)}\n\n`;
}

type ScriptAction = { chunk: string } | { error: unknown };

/** A pull-based ReadableStream that emits exactly one scripted action per
 *  internal `pull()` invocation, which (at the default highWaterMark of 1)
 *  lines up 1:1 with each `reader.read()` call -- so `{ error }` entries
 *  simulate a drop landing exactly after the preceding chunks were
 *  delivered, not before. */
function scriptedStream(actions: ScriptAction[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i >= actions.length) {
        controller.close();
        return;
      }
      const action = actions[i];
      i += 1;
      if ("chunk" in action) {
        controller.enqueue(encoder.encode(action.chunk));
      } else {
        controller.error(action.error);
      }
    },
  });
}

interface RecordedCall {
  url: string;
  headers: Headers;
}

function fetchMockSequence(
  factories: Array<(() => Response) | { reject: unknown }>,
): { fetchImpl: typeof fetch; calls: RecordedCall[] } {
  const calls: RecordedCall[] = [];
  let index = 0;
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), headers: new Headers(init?.headers) });
    const entry = factories[Math.min(index, factories.length - 1)];
    index += 1;
    if (typeof entry === "function") return entry();
    throw entry.reject;
  }) as unknown as typeof fetch;
  return { fetchImpl, calls };
}

// ---------------------------------------------------------------------------
// URL / header construction
// ---------------------------------------------------------------------------

describe("buildAgentEventStreamUrl", () => {
  it("builds a same-origin relative path scoped to the run id, with no query string", () => {
    const url = buildAgentEventStreamUrl(RUN_ID);
    expect(url).toBe(`/v1/demo/runs/${RUN_ID}/events`);
    expect(url.includes("?")).toBe(false);
  });

  it("URL-encodes the run id and never embeds a token", () => {
    const url = buildAgentEventStreamUrl("weird id/with?chars", "/v1/demo");
    expect(url).not.toContain(TOKEN);
    expect(url).toBe("/v1/demo/runs/weird%20id%2Fwith%3Fchars/events");
  });
});

describe("buildAgentEventStreamHeaders", () => {
  it("puts the bearer token only in the Authorization header, never as a query-string-shaped value", () => {
    const headers = buildAgentEventStreamHeaders(TOKEN, null);
    expect(headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    expect(headers.get("Last-Event-ID")).toBeNull();
    // The header set itself carries no key that could leak into a URL.
    expect(Array.from(headers.keys())).not.toContain("token");
  });

  it("sets Last-Event-ID to the last observed sequence number when resuming", () => {
    const headers = buildAgentEventStreamHeaders(TOKEN, 41);
    expect(headers.get("Last-Event-ID")).toBe("41");
  });
});

// ---------------------------------------------------------------------------
// SSE frame parsing
// ---------------------------------------------------------------------------

describe("parseSseFrame", () => {
  it("parses the id:/event:/data: triple", () => {
    const parsed = parseSseFrame('id: 3\nevent: tool.started\ndata: {"a":1}');
    expect(parsed).toEqual({ id: "3", event: "tool.started", data: '{"a":1}' });
  });

  it("returns null for a frame with no data line (heartbeat/comment)", () => {
    expect(parseSseFrame(": heartbeat")).toBeNull();
    expect(parseSseFrame("")).toBeNull();
  });

  it("joins multiple data: lines with a newline", () => {
    const parsed = parseSseFrame("data: line one\ndata: line two");
    expect(parsed?.data).toBe("line one\nline two");
  });
});

describe("extractSseFrames", () => {
  it("splits on the blank-line separator and keeps the trailing partial frame as remainder", () => {
    const { frames, remainder } = extractSseFrames("data: a\n\ndata: b\n\ndata: c (incomple");
    expect(frames).toEqual(["data: a", "data: b"]);
    expect(remainder).toBe("data: c (incomple");
  });

  it("reassembles a frame split across chunk boundaries once the remainder is prepended", () => {
    const first = extractSseFrames("data: hel");
    expect(first.frames).toEqual([]);
    const second = extractSseFrames(first.remainder + "lo\n\n");
    expect(second.frames).toEqual(["data: hello"]);
  });
});

// ---------------------------------------------------------------------------
// isTerminalAgentEvent
// ---------------------------------------------------------------------------

describe("isTerminalAgentEvent", () => {
  it("treats workflow.completed and workflow.failed as terminal", () => {
    expect(isTerminalAgentEvent(GOLDEN_AGENT_EVENTS["workflow.completed"])).toBe(true);
    expect(isTerminalAgentEvent(GOLDEN_AGENT_EVENTS["workflow.failed"])).toBe(true);
  });

  it("treats every other event type as non-terminal", () => {
    expect(isTerminalAgentEvent(GOLDEN_AGENT_EVENTS["workflow.started"])).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// End-to-end client behaviour
// ---------------------------------------------------------------------------

describe("AgentEventStreamClient", () => {
  it("never places the bearer token in the request URL across a full run, including a reconnect", async () => {
    const { fetchImpl, calls } = fetchMockSequence([
      () =>
        new Response(
          scriptedStream([
            { chunk: makeFrame(0, "workflow.started") },
            { chunk: makeFrame(1, "workflow.status") },
            { chunk: makeFrame(2, "tool.started") },
            { error: new Error("simulated connection drop") },
          ]),
          { status: 200 },
        ),
      () =>
        new Response(
          scriptedStream([
            { chunk: makeFrame(3, "tool.completed") },
            { chunk: makeFrame(4, "workflow.completed") },
          ]),
          { status: 200 },
        ),
    ]);

    const events: number[] = [];
    let closeReason: AgentEventStreamCloseReason | undefined;

    const client = new AgentEventStreamClient(
      { runId: RUN_ID, token: TOKEN, fetchImpl, scheduleReconnect: (_delay, run) => run() },
      {
        onEvent: (event) => events.push(event.sequence_number),
        onClose: (reason) => {
          closeReason = reason;
        },
      },
    );

    await client.start();

    expect(closeReason).toBe("terminal-event");
    expect(calls).toHaveLength(2);
    for (const call of calls) {
      expect(call.url).not.toContain(TOKEN);
      expect(call.url.includes("?")).toBe(false);
      expect(call.headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    }
    // Sanity: the token really was sent, just never in the URL.
    expect(calls.every((c) => c.headers.get("Authorization") === `Bearer ${TOKEN}`)).toBe(true);

    // Reconnect resumes gaplessly and without duplicates.
    expect(events).toEqual([0, 1, 2, 3, 4]);
    expect(new Set(events).size).toBe(events.length);
  });

  it("reconnects with Last-Event-ID set to the last observed sequence number, not 0 and not an arbitrary value", async () => {
    const { fetchImpl, calls } = fetchMockSequence([
      () =>
        new Response(
          scriptedStream([
            { chunk: makeFrame(0, "workflow.started") },
            { chunk: makeFrame(1, "workflow.status") },
            { chunk: makeFrame(2, "tool.started") },
            { error: new Error("simulated connection drop") },
          ]),
          { status: 200 },
        ),
      () =>
        new Response(scriptedStream([{ chunk: makeFrame(3, "workflow.completed") }]), { status: 200 }),
    ]);

    const client = new AgentEventStreamClient(
      { runId: RUN_ID, token: TOKEN, fetchImpl, scheduleReconnect: (_d, run) => run() },
      { onEvent: () => {} },
    );

    await client.start();

    expect(calls).toHaveLength(2);
    expect(calls[0]!.headers.get("Last-Event-ID")).toBeNull();
    expect(calls[1]!.headers.get("Last-Event-ID")).toBe("2");
  });

  it("surfaces the dropped connection to onError as a distinct, retryable network error", async () => {
    const { fetchImpl } = fetchMockSequence([
      () =>
        new Response(
          scriptedStream([
            { chunk: makeFrame(0, "workflow.started") },
            { error: new Error("simulated connection drop") },
          ]),
          { status: 200 },
        ),
      () => new Response(scriptedStream([{ chunk: makeFrame(1, "workflow.completed") }]), { status: 200 }),
    ]);

    const errors: Array<{ error: AgentEventStreamError; willRetry: boolean }> = [];
    const client = new AgentEventStreamClient(
      { runId: RUN_ID, token: TOKEN, fetchImpl, scheduleReconnect: (_d, run) => run() },
      { onEvent: () => {}, onError: (error, ctx) => errors.push({ error, willRetry: ctx.willRetry }) },
    );

    await client.start();

    expect(errors).toHaveLength(1);
    expect(errors[0]!.error).toBeInstanceOf(AgentEventStreamNetworkError);
    expect(errors[0]!.willRetry).toBe(true);
  });

  it.each([
    [401, "unauthorized"],
    [404, "not_found"],
    [500, "server_error"],
  ] as const)("distinguishes a %d response as kind %s, never collapsing it into an opaque error", async (status, kind) => {
    const { fetchImpl } = fetchMockSequence([() => new Response(null, { status })]);

    const errors: Array<{ error: AgentEventStreamError; willRetry: boolean }> = [];
    let closeReason: AgentEventStreamCloseReason | undefined;
    const client = new AgentEventStreamClient(
      { runId: RUN_ID, token: TOKEN, fetchImpl, maxReconnectAttempts: 0 },
      {
        onEvent: () => {},
        onError: (error, ctx) => errors.push({ error, willRetry: ctx.willRetry }),
        onClose: (reason) => {
          closeReason = reason;
        },
      },
    );

    await client.start();

    expect(errors).toHaveLength(1);
    const error = errors[0]!.error;
    expect(error).toBeInstanceOf(AgentEventStreamHttpError);
    expect((error as AgentEventStreamHttpError).status).toBe(status);
    expect((error as AgentEventStreamHttpError).kind).toBe(kind);
    expect(closeReason).toBe("http-error");
  });

  it("distinguishes a 401 from a 404 from a 500 from each other, not just from success", async () => {
    const results = await Promise.all(
      [401, 404, 500].map(async (status) => {
        const { fetchImpl } = fetchMockSequence([() => new Response(null, { status })]);
        let captured: AgentEventStreamError | undefined;
        const client = new AgentEventStreamClient(
          { runId: RUN_ID, token: TOKEN, fetchImpl, maxReconnectAttempts: 0 },
          { onEvent: () => {}, onError: (error) => (captured = error) },
        );
        await client.start();
        return captured;
      }),
    );

    const [unauthorized, notFound, serverError] = results as AgentEventStreamHttpError[];
    expect(new Set([unauthorized.kind, notFound.kind, serverError.kind]).size).toBe(3);
    expect(new Set([unauthorized.status, notFound.status, serverError.status]).size).toBe(3);
  });

  it("distinguishes a network-level failure (fetch rejects) from an HTTP error response", async () => {
    const { fetchImpl } = fetchMockSequence([{ reject: new TypeError("Failed to fetch") }]);

    let captured: AgentEventStreamError | undefined;
    const client = new AgentEventStreamClient(
      { runId: RUN_ID, token: TOKEN, fetchImpl, maxReconnectAttempts: 0 },
      { onEvent: () => {}, onError: (error) => (captured = error) },
    );

    await client.start();

    expect(captured).toBeInstanceOf(AgentEventStreamNetworkError);
    expect(captured).not.toBeInstanceOf(AgentEventStreamHttpError);
  });

  it("gives up after the configured maximum reconnect attempts and reports a terminal failure, instead of retrying a persistently-failing connection forever", async () => {
    // Every attempt fails the same way (a deterministically-failing
    // stream, e.g. the poison-frame scenario Review's mutation surfaced
    // as a 5s test timeout when retries were unbounded).
    const fetchImpl = vi.fn(async () => {
      throw new Error("this endpoint never comes back");
    }) as unknown as typeof fetch;

    const errors: Array<{ error: AgentEventStreamError; attempt: number; willRetry: boolean }> = [];
    let closeReason: AgentEventStreamCloseReason | undefined;

    const client = new AgentEventStreamClient(
      { runId: RUN_ID, token: TOKEN, fetchImpl, maxReconnectAttempts: 3, scheduleReconnect: (_d, run) => run() },
      {
        onEvent: () => {},
        onError: (error, ctx) => errors.push({ error, attempt: ctx.attempt, willRetry: ctx.willRetry }),
        onClose: (reason) => {
          closeReason = reason;
        },
      },
    );

    await client.start();

    // 1 initial attempt + 3 retries = 4 fetch calls, then it stops.
    expect(fetchImpl).toHaveBeenCalledTimes(4);
    expect(errors).toHaveLength(4);
    expect(errors.map((e) => e.attempt)).toEqual([1, 2, 3, 4]);
    expect(errors.slice(0, 3).every((e) => e.willRetry)).toBe(true);
    expect(errors[3]!.willRetry).toBe(false);
    expect(closeReason).toBe("exhausted-reconnect-attempts");
  });

  it("defaults to a finite number of reconnect attempts (AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS), not unlimited", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("this endpoint never comes back");
    }) as unknown as typeof fetch;

    let closeReason: AgentEventStreamCloseReason | undefined;

    // No maxReconnectAttempts configured -- exercising the module's own
    // default. reconnectDelayMs is overridden to 0 purely so the test
    // doesn't have to sit through real backoff; the attempt *count* is
    // the module's default, unmodified.
    const client = new AgentEventStreamClient(
      { runId: RUN_ID, token: TOKEN, fetchImpl, reconnectDelayMs: 0, scheduleReconnect: (_d, run) => run() },
      { onEvent: () => {}, onClose: (reason) => (closeReason = reason) },
    );

    await client.start();

    expect(AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS).toBeGreaterThan(0);
    expect(Number.isFinite(AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS)).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS + 1);
    expect(closeReason).toBe("exhausted-reconnect-attempts");
  });

  it("stops the read loop cleanly on AbortController.abort(): no further callback fires, and abort itself raises no unhandled rejection", async () => {
    const unhandled: unknown[] = [];
    const onUnhandledRejection = (reason: unknown) => unhandled.push(reason);
    process.on("unhandledRejection", onUnhandledRejection);

    try {
      let resolveFirstEvent!: () => void;
      const firstEventReceived = new Promise<void>((resolve) => {
        resolveFirstEvent = resolve;
      });

      const events: number[] = [];
      let eventsAfterAbort = 0;
      let aborted = false;
      let closeReason: AgentEventStreamCloseReason | undefined;

      const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        const signal = init?.signal ?? null;
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(makeFrame(0, "workflow.started")));
            signal?.addEventListener("abort", () => {
              controller.error(new DOMException("The operation was aborted.", "AbortError"));
            });
            // No close()/error() otherwise -- the stream hangs open until aborted.
          },
        });
        return new Response(stream, { status: 200 });
      }) as unknown as typeof fetch;

      const { abort, done } = openAgentEventStream(
        { runId: RUN_ID, token: TOKEN, fetchImpl },
        {
          onEvent: (event) => {
            events.push(event.sequence_number);
            if (aborted) eventsAfterAbort += 1;
            resolveFirstEvent();
          },
          onClose: (reason) => {
            closeReason = reason;
          },
        },
      );

      await firstEventReceived;
      aborted = true;
      abort();
      await done;

      expect(events).toEqual([0]);
      expect(eventsAfterAbort).toBe(0);
      expect(closeReason).toBe("aborted");
    } finally {
      process.off("unhandledRejection", onUnhandledRejection);
    }

    expect(unhandled).toEqual([]);
  });

  it("abort() is idempotent and safe to call before the first response arrives", async () => {
    // Mirrors real fetch(): a pending request rejects with AbortError once
    // its signal fires, instead of hanging forever.
    const fetchImpl = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      });
    }) as unknown as typeof fetch;

    let closeReason: AgentEventStreamCloseReason | undefined;
    const { abort, done } = openAgentEventStream(
      { runId: RUN_ID, token: TOKEN, fetchImpl },
      { onEvent: () => {}, onClose: (reason) => (closeReason = reason) },
    );

    abort();
    abort();
    await done;

    expect(closeReason).toBe("aborted");
  });

  it("releases the ReadableStream reader lock when the stream is aborted mid-read (no leaked reader)", async () => {
    // Spies on the real global ReadableStreamDefaultReader -- this is the
    // exact class response.body.getReader() returns, so it observes every
    // releaseLock() call the implementation makes, without needing the
    // implementation to expose its internal reader.
    const releaseLockSpy = vi.spyOn(ReadableStreamDefaultReader.prototype, "releaseLock");

    try {
      let resolveFirstEvent!: () => void;
      const firstEventReceived = new Promise<void>((resolve) => {
        resolveFirstEvent = resolve;
      });

      const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        const signal = init?.signal ?? null;
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(makeFrame(0, "workflow.started")));
            signal?.addEventListener("abort", () => {
              controller.error(new DOMException("The operation was aborted.", "AbortError"));
            });
          },
        });
        return new Response(stream, { status: 200 });
      }) as unknown as typeof fetch;

      const callsBeforeThisStream = releaseLockSpy.mock.calls.length;

      const { abort, done } = openAgentEventStream(
        { runId: RUN_ID, token: TOKEN, fetchImpl },
        { onEvent: () => resolveFirstEvent() },
      );

      await firstEventReceived;
      abort();
      await done;

      expect(releaseLockSpy.mock.calls.length).toBeGreaterThan(callsBeforeThisStream);
    } finally {
      releaseLockSpy.mockRestore();
    }
  });

  it("surfaces a malformed/unrecognized event_type as an inspectable parse error and keeps streaming instead of choking", async () => {
    const reservedDeltaFrame = makeFrame(0, "assistant.text.delta", { text_delta: "hi" });
    const notJsonFrame = "id: 1\nevent: workflow.status\ndata: { not valid json\n\n";

    const { fetchImpl } = fetchMockSequence([
      () =>
        new Response(
          scriptedStream([
            { chunk: reservedDeltaFrame },
            { chunk: notJsonFrame },
            { chunk: makeFrame(2, "workflow.completed") },
          ]),
          { status: 200 },
        ),
    ]);

    const parseErrors: AgentEventParseError[] = [];
    const events: number[] = [];
    let closeReason: AgentEventStreamCloseReason | undefined;

    const client = new AgentEventStreamClient(
      { runId: RUN_ID, token: TOKEN, fetchImpl },
      {
        onEvent: (event) => events.push(event.sequence_number),
        onParseError: (error) => parseErrors.push(error),
        onClose: (reason) => (closeReason = reason),
      },
    );

    await client.start();

    expect(parseErrors).toHaveLength(2);
    expect(parseErrors[0]).toBeInstanceOf(AgentEventParseError);
    expect(parseErrors[0]!.message).toContain("assistant.text.delta");
    expect(parseErrors[0]!.rawFrame).toContain("assistant.text.delta");
    expect(parseErrors[1]!.message.toLowerCase()).toContain("json");

    // The reserved/malformed frames never reach onEvent...
    expect(events).toEqual([2]);
    // ...but the read loop kept going and reached the clean terminal close.
    expect(closeReason).toBe("terminal-event");
  });

  it("binds to @juli/contracts's validateAgentEvent by identity, not by re-implementing an equivalent parser locally", async () => {
    // A source-text scan (see "module dependency hygiene" below) can only
    // see that a `from "@juli/contracts"` import statement exists -- it
    // cannot see whether the code that actually runs at parse time is the
    // literal imported function or a separately-declared, structurally
    // faithful lookalike (TypeScript's type system is structural, so a
    // faithful duplicate type-checks either way). Spying on the real
    // export binds this assertion to *value* identity instead: a
    // locally-reimplemented validator, however faithful, is a different
    // function object and would never trigger this spy.
    const validateSpy = vi.spyOn(contracts, "validateAgentEvent");
    try {
      const { fetchImpl } = fetchMockSequence([
        () =>
          new Response(scriptedStream([{ chunk: makeFrame(0, "workflow.completed") }]), { status: 200 }),
      ]);

      const events: number[] = [];
      const client = new AgentEventStreamClient(
        { runId: RUN_ID, token: TOKEN, fetchImpl },
        { onEvent: (event) => events.push(event.sequence_number) },
      );

      await client.start();

      expect(events).toEqual([0]);
      expect(validateSpy).toHaveBeenCalled();
      expect(validateSpy.mock.calls.length).toBeGreaterThanOrEqual(1);
    } finally {
      validateSpy.mockRestore();
    }
  });

  it("accepts @juli/contracts's GOLDEN_AGENT_EVENTS directly through onEvent -- a type-level smoke test alongside the identity spy above", () => {
    const received: contracts.AgentEvent[] = [];
    const handlers: AgentEventStreamHandlers = {
      onEvent: (event) => {
        received.push(event);
      },
    };

    // No cast, no `as AgentEvent` escape hatch: every golden fixture typed
    // against @juli/contracts's own AgentEvent flows straight into the
    // handler's parameter type. (This alone would not catch a faithful
    // structural duplicate -- only the identity spy above does that -- but
    // it does catch the kind of divergent local redeclaration Review's
    // mutation produced, the same way tsc caught it incidentally there.)
    for (const event of Object.values(contracts.GOLDEN_AGENT_EVENTS)) {
      handlers.onEvent(event);
    }

    expect(received).toHaveLength(Object.keys(contracts.GOLDEN_AGENT_EVENTS).length);
  });
});

// ---------------------------------------------------------------------------
// Dependency hygiene: fetch + ReadableStream only, no EventSource, no new
// HTTP client library, imports only from @juli/contracts.
// ---------------------------------------------------------------------------

describe("module dependency hygiene", () => {
  const source = readFileSync(join(process.cwd(), "src/lib/agent-event-stream.ts"), "utf-8");

  it("never constructs a native EventSource", () => {
    expect(source).not.toMatch(/\bnew\s+EventSource\b/);
    expect(source).not.toMatch(/\bEventSource\b\s*\(/);
  });

  it("uses fetch and ReadableStream primitives", () => {
    expect(source).toContain("fetch(");
    expect(source).toContain("getReader()");
  });

  it("imports only from @juli/contracts (no HTTP client library, new or otherwise)", () => {
    const importSources = Array.from(source.matchAll(/from\s+"([^"]+)"/g)).map((m) => m[1]);
    expect(importSources.length).toBeGreaterThan(0);
    for (const importSource of importSources) {
      expect(importSource).toBe("@juli/contracts");
    }
  });
});
