import { validateAgentEvent, type AgentEvent } from "@juli/contracts";

/**
 * Fetch-streaming SSE client transport for `GET /v1/demo/runs/{run_id}/events`
 * (ADR-074 decision 5, #1132 / AGT-W3B-UI).
 *
 * Deliberately built on `fetch` + `ReadableStream`, never native
 * `EventSource`, for four testable properties:
 *  - Bearer auth stays in request headers -- `EventSource` cannot set
 *    headers, which would force the token into the URL (logs, history,
 *    referrers). See `buildAgentEventStreamHeaders`.
 *  - Reconnect is owned here, not by the browser: it resumes from the last
 *    observed `sequence_number` via the `Last-Event-ID` header, never from
 *    0 and never from an arbitrary point. See `AgentEventStreamClient`.
 *  - Failures are inspectable: 401 / 404 / 500 / network failure are
 *    distinct error types, not one opaque stream error. See
 *    `AgentEventStreamHttpError` / `AgentEventStreamNetworkError`.
 *  - `AbortController` cancels cleanly: no further callback fires after
 *    abort, no unhandled rejection from the abort itself.
 *
 * Transport only -- this module ships no reducer and no view. P-UI (W4-B)
 * owns turning `AgentEvent`s into UI state. Nothing under `apps/demo`
 * imports this module in this slice (see the release evidence plan for
 * issue #1132): it becomes reachable only when a later P-UI slice wires it
 * into a page.
 *
 * Imports only from `@juli/contracts` and browser/runtime primitives
 * (`fetch`, `Headers`, `AbortController`, `ReadableStream`, `TextDecoder`)
 * -- no HTTP client library, new or otherwise.
 */

// ---------------------------------------------------------------------------
// Wire-level constants
// ---------------------------------------------------------------------------

/** Default same-origin base path (demo workspace contract #397: no client
 *  env API base -- relative URLs only, proxied at the edge). */
export const AGENT_EVENT_STREAM_DEFAULT_BASE_URL = "/v1/demo";

/** SSE reconnect header carrying the last observed `sequence_number`,
 *  matching P8-4's server-side resume contract (`Last-Event-ID` or
 *  `?after=`; this client uses the header). */
export const AGENT_EVENT_STREAM_LAST_EVENT_ID_HEADER = "Last-Event-ID";

export function buildAgentEventStreamUrl(
  runId: string,
  baseUrl: string = AGENT_EVENT_STREAM_DEFAULT_BASE_URL,
): string {
  return `${baseUrl}/runs/${encodeURIComponent(runId)}/events`;
}

/**
 * The bearer token and the resume cursor are both request headers -- never
 * query parameters -- so neither ever appears in the request URL, and by
 * extension never in a log line, browser history entry, or referrer.
 */
export function buildAgentEventStreamHeaders(
  token: string,
  lastSequenceNumber: number | null,
): Headers {
  const headers = new Headers();
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept", "text/event-stream");
  if (lastSequenceNumber !== null) {
    headers.set(AGENT_EVENT_STREAM_LAST_EVENT_ID_HEADER, String(lastSequenceNumber));
  }
  return headers;
}

// ---------------------------------------------------------------------------
// Inspectable failure types -- 401 vs 404 vs 500 vs network failure vs a
// malformed frame are distinct types, never collapsed into one opaque error.
// ---------------------------------------------------------------------------

export type AgentEventStreamHttpErrorKind =
  | "unauthorized"
  | "not_found"
  | "server_error"
  | "http_error";

function classifyHttpStatus(status: number): AgentEventStreamHttpErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status >= 500) return "server_error";
  return "http_error";
}

/** A non-2xx HTTP response to the stream request. `.status` and `.kind`
 *  let a caller distinguish 401 vs 404 vs 500 without string-matching. */
export class AgentEventStreamHttpError extends Error {
  readonly status: number;
  readonly kind: AgentEventStreamHttpErrorKind;

  constructor(status: number, statusText?: string) {
    super(`agent event stream request failed with status ${status}${statusText ? ` (${statusText})` : ""}`);
    this.name = "AgentEventStreamHttpError";
    this.status = status;
    this.kind = classifyHttpStatus(status);
  }
}

/** `fetch()` itself rejected, or the body reader rejected, for a reason
 *  other than an intentional `AbortController.abort()` -- a DNS failure,
 *  a dropped connection mid-stream, etc. Distinct from an HTTP error
 *  response, which at least reached the server. */
export class AgentEventStreamNetworkError extends Error {
  override readonly cause?: unknown;

  constructor(cause: unknown) {
    super(`agent event stream network failure: ${cause instanceof Error ? cause.message : String(cause)}`);
    this.name = "AgentEventStreamNetworkError";
    this.cause = cause;
  }
}

/** A `data:` frame that is not valid JSON, or that fails
 *  `validateAgentEvent` (unknown/reserved `event_type`, missing field,
 *  etc). Surfaced per-frame via `onParseError` -- it does not stop the
 *  read loop and is never silently dropped. */
export class AgentEventParseError extends Error {
  readonly rawFrame: string;
  override readonly cause?: unknown;

  constructor(message: string, rawFrame: string, cause?: unknown) {
    super(message);
    this.name = "AgentEventParseError";
    this.rawFrame = rawFrame;
    this.cause = cause;
  }
}

export type AgentEventStreamError = AgentEventStreamHttpError | AgentEventStreamNetworkError;

// ---------------------------------------------------------------------------
// SSE frame parsing -- splits the raw byte stream into `id:`/`event:`/
// `data:` frames without assuming chunk boundaries align with frame
// boundaries.
// ---------------------------------------------------------------------------

export interface ParsedSseFrame {
  id: string | null;
  event: string | null;
  data: string;
}

/** Splits a decoded text buffer on the SSE frame separator (`\n\n`).
 *  Returns the complete frames found and the leftover partial frame, which
 *  the caller must prepend to the next chunk. */
export function extractSseFrames(buffer: string): { frames: string[]; remainder: string } {
  const frames: string[] = [];
  let rest = buffer;
  let separatorIndex = rest.indexOf("\n\n");
  while (separatorIndex !== -1) {
    frames.push(rest.slice(0, separatorIndex));
    rest = rest.slice(separatorIndex + 2);
    separatorIndex = rest.indexOf("\n\n");
  }
  return { frames, remainder: rest };
}

/** Parses one raw frame's `id:`/`event:`/`data:` lines. Returns `null` for
 *  a frame with no `data:` line (e.g. a bare heartbeat comment). Multiple
 *  `data:` lines are joined with `\n`, per the SSE spec. */
export function parseSseFrame(rawFrame: string): ParsedSseFrame | null {
  let id: string | null = null;
  let event: string | null = null;
  const dataLines: string[] = [];

  for (const line of rawFrame.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    if (line.startsWith("id:")) {
      id = line.slice(3).trim();
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) return null;
  return { id, event, data: dataLines.join("\n") };
}

// ---------------------------------------------------------------------------
// Event-level helpers
// ---------------------------------------------------------------------------

/** The two terminal event types (ADR-074 d.2): `workflow.completed` and
 *  the failure-class terminal `workflow.failed`. A terminal event closes
 *  the stream cleanly -- it is not a drop, and does not trigger reconnect. */
export function isTerminalAgentEvent(event: AgentEvent): boolean {
  return event.event_type === "workflow.completed" || event.event_type === "workflow.failed";
}

// ---------------------------------------------------------------------------
// Public client
// ---------------------------------------------------------------------------

export interface AgentEventStreamHandlers {
  /** Fires once per successfully parsed, validated event -- never for a
   *  malformed frame or a reserved/unknown `event_type`. */
  onEvent: (event: AgentEvent) => void;
  /** Fires for a frame that is not valid JSON, or that fails
   *  `validateAgentEvent` -- including a hypothetical reserved
   *  `assistant.text.delta` frame. Never crashes the read loop. */
  onParseError?: (error: AgentEventParseError) => void;
  /** Fires for an HTTP or network-level connection failure. `willRetry`
   *  tells the caller whether the client will attempt to reconnect. */
  onError?: (error: AgentEventStreamError, context: { attempt: number; willRetry: boolean }) => void;
  /** Fires exactly once, when the client stops for good. */
  onClose?: (reason: AgentEventStreamCloseReason) => void;
}

export type AgentEventStreamCloseReason =
  | "terminal-event"
  | "aborted"
  | "http-error"
  | "exhausted-reconnect-attempts";

export interface AgentEventStreamConfig {
  runId: string;
  /** Bearer token -- sent only in the `Authorization` header, never in the
   *  URL. */
  token: string;
  baseUrl?: string;
  /** Injectable for tests; defaults to the global `fetch`. */
  fetchImpl?: typeof fetch;
  /** Maximum reconnect attempts after a drop. Defaults to
   *  `AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS` (see that
   *  constant for the reasoning) -- **not** unlimited. A 401/404 response
   *  never retries regardless of this setting -- the credentials or the
   *  run id are wrong, not the network. */
  maxReconnectAttempts?: number;
  /** Delay before each reconnect attempt, or a function of the attempt
   *  number (1-indexed) for backoff. Defaults to capped exponential
   *  backoff. */
  reconnectDelayMs?: number | ((attempt: number) => number);
  /** Injectable scheduler for tests; defaults to `setTimeout`. */
  scheduleReconnect?: (delayMs: number, run: () => void) => void;
}

interface ConnectionOutcome {
  reason: "terminal-event" | "aborted" | "stream-ended";
}

/**
 * Finite by design. An "unlimited retries, capped backoff" default sounds
 * safe -- it's not a busy-loop, each attempt is seconds apart -- but it is
 * only safe because this module has no caller yet. The moment P-UI (W4-B)
 * wires this in, "unlimited" becomes "silently retries forever against a
 * deterministically-failing stream," with no terminal `onClose` ever
 * reaching the UI to let it show an error state. 10 attempts, at the
 * default capped-exponential backoff (1s, 2s, 4s, 8s, 15s, 15s, ...), is
 * a little over two minutes -- long enough to ride out a real transient
 * blip, short enough that a persistent failure (a dead run, a
 * misconfigured endpoint, a poison frame the server keeps re-sending)
 * surfaces a terminal `exhausted-reconnect-attempts` close instead of
 * hanging open indefinitely. Fully overridable via `maxReconnectAttempts`
 * for a caller that wants different behavior (e.g. unlimited, by passing
 * `Number.POSITIVE_INFINITY`).
 */
export const AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS = 10;

function defaultReconnectDelayMs(attempt: number): number {
  return Math.min(1000 * 2 ** (attempt - 1), 15_000);
}

function defaultScheduleReconnect(delayMs: number, run: () => void): void {
  setTimeout(run, delayMs);
}

function handleFrame(
  parsed: ParsedSseFrame,
  handlers: AgentEventStreamHandlers,
): { sequenceNumber: number | null; terminal: boolean } {
  let raw: unknown;
  try {
    raw = JSON.parse(parsed.data);
  } catch (cause) {
    handlers.onParseError?.(
      new AgentEventParseError("agent event frame data is not valid JSON", parsed.data, cause),
    );
    return { sequenceNumber: null, terminal: false };
  }

  let event: AgentEvent;
  try {
    event = validateAgentEvent(raw);
  } catch (cause) {
    // Includes a reserved/unknown event_type (e.g. a hypothetical
    // `assistant.text.delta`) -- validateAgentEvent rejects it by name.
    // Surfaced as an inspectable parse error; the read loop continues.
    handlers.onParseError?.(
      new AgentEventParseError(
        cause instanceof Error ? cause.message : "agent event failed validation",
        parsed.data,
        cause,
      ),
    );
    return { sequenceNumber: null, terminal: false };
  }

  handlers.onEvent(event);
  return { sequenceNumber: event.sequence_number, terminal: isTerminalAgentEvent(event) };
}

async function runConnection(
  config: AgentEventStreamConfig,
  handlers: AgentEventStreamHandlers,
  afterSequenceNumber: number | null,
  signal: AbortSignal,
  fetchImpl: typeof fetch,
  onSequenceNumber: (sequenceNumber: number) => void,
): Promise<ConnectionOutcome> {
  let response: Response;
  try {
    response = await fetchImpl(buildAgentEventStreamUrl(config.runId, config.baseUrl), {
      method: "GET",
      headers: buildAgentEventStreamHeaders(config.token, afterSequenceNumber),
      signal,
    });
  } catch (cause) {
    if (signal.aborted) return { reason: "aborted" };
    throw new AgentEventStreamNetworkError(cause);
  }

  if (!response.ok) {
    throw new AgentEventStreamHttpError(response.status, response.statusText);
  }
  if (!response.body) {
    throw new AgentEventStreamNetworkError(new Error("agent event stream response has no readable body"));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      let step: ReadableStreamReadResult<Uint8Array>;
      try {
        step = await reader.read();
      } catch (cause) {
        if (signal.aborted) return { reason: "aborted" };
        throw new AgentEventStreamNetworkError(cause);
      }
      if (signal.aborted) return { reason: "aborted" };
      if (step.done) break;

      buffer += decoder.decode(step.value, { stream: true });
      const { frames, remainder } = extractSseFrames(buffer);
      buffer = remainder;

      for (const rawFrame of frames) {
        const parsed = parseSseFrame(rawFrame);
        if (!parsed) continue; // heartbeat / comment-only frame

        const { sequenceNumber, terminal } = handleFrame(parsed, handlers);
        if (sequenceNumber !== null) onSequenceNumber(sequenceNumber);
        if (terminal) return { reason: "terminal-event" };
        if (signal.aborted) return { reason: "aborted" };
      }
    }
    return { reason: "stream-ended" };
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Already released (e.g. the stream errored out from under us).
    }
  }
}

/**
 * Owns one run's SSE connection end to end: connects, parses frames,
 * reconnects from the last observed `sequence_number` on an unexpected
 * drop, and stops cleanly on a terminal event, an unrecoverable error, or
 * `abort()`.
 */
export class AgentEventStreamClient {
  private readonly config: AgentEventStreamConfig;
  private readonly handlers: AgentEventStreamHandlers;
  private readonly fetchImpl: typeof fetch;
  private readonly abortController = new AbortController();
  private lastSequenceNumber: number | null = null;
  private reconnectAttempt = 0;
  private closed = false;

  constructor(config: AgentEventStreamConfig, handlers: AgentEventStreamHandlers) {
    this.config = config;
    this.handlers = handlers;
    this.fetchImpl = config.fetchImpl ?? fetch;
  }

  /** The last `sequence_number` this client has successfully delivered to
   *  `onEvent`, or `null` before the first event. Exposed for callers that
   *  want to inspect resume progress; the client also uses this
   *  internally to build the `Last-Event-ID` header on reconnect. */
  get lastObservedSequenceNumber(): number | null {
    return this.lastSequenceNumber;
  }

  /** Begins streaming. Resolves once the client reaches a terminal state
   *  (terminal event, abort, or an unrecoverable/exhausted error) --
   *  never rejects. All failures are surfaced through `onError`/`onClose`
   *  instead of a thrown/rejected value. */
  async start(): Promise<void> {
    while (!this.closed) {
      if (this.abortController.signal.aborted) {
        this.finish("aborted");
        return;
      }

      let outcome: ConnectionOutcome;
      try {
        outcome = await runConnection(
          this.config,
          this.handlers,
          this.lastSequenceNumber,
          this.abortController.signal,
          this.fetchImpl,
          (sequenceNumber) => {
            this.lastSequenceNumber = sequenceNumber;
          },
        );
      } catch (error) {
        if (this.abortController.signal.aborted) {
          this.finish("aborted");
          return;
        }

        const streamError =
          error instanceof AgentEventStreamHttpError || error instanceof AgentEventStreamNetworkError
            ? error
            : new AgentEventStreamNetworkError(error);

        // 401/404 mean the credentials or the run id are wrong, not that
        // the connection dropped -- retrying can't fix either, so these
        // never reconnect regardless of maxReconnectAttempts.
        const isUnrecoverableHttpError =
          streamError instanceof AgentEventStreamHttpError &&
          (streamError.kind === "unauthorized" || streamError.kind === "not_found");

        this.reconnectAttempt += 1;
        const maxAttempts = this.config.maxReconnectAttempts ?? AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS;
        const willRetry = !isUnrecoverableHttpError && this.reconnectAttempt <= maxAttempts;

        this.handlers.onError?.(streamError, { attempt: this.reconnectAttempt, willRetry });

        if (!willRetry) {
          this.finish(
            streamError instanceof AgentEventStreamHttpError ? "http-error" : "exhausted-reconnect-attempts",
          );
          return;
        }

        await this.waitBeforeReconnect();
        continue;
      }

      if (outcome.reason === "aborted") {
        this.finish("aborted");
        return;
      }
      if (outcome.reason === "terminal-event") {
        this.finish("terminal-event");
        return;
      }

      // "stream-ended": the server closed the connection without a
      // terminal event (e.g. a heartbeat timeout). Reconnect from
      // lastSequenceNumber -- never from 0, never from an arbitrary point.
      this.reconnectAttempt += 1;
      const maxAttempts = this.config.maxReconnectAttempts ?? AGENT_EVENT_STREAM_DEFAULT_MAX_RECONNECT_ATTEMPTS;
      if (this.reconnectAttempt > maxAttempts) {
        this.finish("exhausted-reconnect-attempts");
        return;
      }
      await this.waitBeforeReconnect();
    }
  }

  /** Cancels the stream. Safe to call more than once or before `start()`
   *  resolves; idempotent. No further `onEvent`/`onParseError`/`onError`
   *  callback fires after this returns, and the abort itself never raises
   *  an unhandled rejection -- `start()`'s promise simply resolves. */
  abort(): void {
    if (this.abortController.signal.aborted) return;
    this.abortController.abort();
  }

  private finish(reason: AgentEventStreamCloseReason): void {
    if (this.closed) return;
    this.closed = true;
    this.handlers.onClose?.(reason);
  }

  private async waitBeforeReconnect(): Promise<void> {
    const configured = this.config.reconnectDelayMs;
    const delayMs =
      typeof configured === "function"
        ? configured(this.reconnectAttempt)
        : configured ?? defaultReconnectDelayMs(this.reconnectAttempt);
    const schedule = this.config.scheduleReconnect ?? defaultScheduleReconnect;
    await new Promise<void>((resolve) => schedule(delayMs, resolve));
  }
}

/**
 * Convenience entry point: constructs an `AgentEventStreamClient`, starts
 * it, and returns a handle to cancel it. `done` resolves (never rejects)
 * once the client reaches a terminal state.
 */
export function openAgentEventStream(
  config: AgentEventStreamConfig,
  handlers: AgentEventStreamHandlers,
): { abort: () => void; done: Promise<void> } {
  const client = new AgentEventStreamClient(config, handlers);
  return { abort: () => client.abort(), done: client.start() };
}
