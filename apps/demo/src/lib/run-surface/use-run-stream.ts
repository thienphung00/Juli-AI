"use client";

/**
 * `useRunStream(runId)` — the impure half of #1315 (ADR-076 decision 6).
 *
 * BUILDS ON #1132's CLIENT, DELIBERATELY. `openAgentEventStream` already tracks
 * `lastSeq`, reconnects with capped backoff, sends `Last-Event-ID`, and carries
 * the bearer token in a header rather than the URL. Writing a second client here
 * would mean a second set of reconnect semantics to keep in step with the
 * server's replay contract, and the two would drift. This hook owns exactly what
 * the client does not: accumulating events and handing them to the pure reducer.
 *
 * A STREAM ERROR AND A RUN ERROR ARE DIFFERENT THINGS. This is the whole reason
 * the hook returns two values instead of one. A dropped connection means "we
 * lost the pipe, we are retrying" — the run is very likely still executing on
 * the server. A `workflow.failed` event means the run itself is over and failed.
 * Collapsing them tells a seller their run died because their wifi blinked, and
 * hides a genuine failure behind a spinner. `streamStatus` carries the first;
 * `view.terminal` carries the second; a test asserts they are not the same
 * value.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import type { AgentEvent } from "@juli/contracts";

import {
  openAgentEventStream,
  type AgentEventStreamCloseReason,
  type AgentEventStreamError,
} from "../agent-event-stream";
import { reduceRunView, type RunViewState } from "./reduce-run-view";

/** The CONNECTION's state. Never the run's -- see the module docstring. */
export type RunStreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed";

export interface UseRunStreamOptions {
  /** Bearer token for the stream. Absent means "do not connect yet". */
  token?: string;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  /** Seeds the view without connecting -- used by tests and by a finished run
   *  rendered from already-fetched events. */
  initialEvents?: readonly AgentEvent[];
  enabled?: boolean;
}

export interface UseRunStreamResult {
  /** Derived purely from the events seen so far. */
  readonly view: RunViewState;
  /** The connection, not the run. */
  readonly streamStatus: RunStreamStatus;
  /** Set only for connection failures. A failed RUN is `view.terminal`. */
  readonly streamError?: AgentEventStreamError;
  readonly closeReason?: AgentEventStreamCloseReason;
  /** The reconnect cursor the client sends as `Last-Event-ID`. */
  readonly lastSequence: number;
}

export function useRunStream(
  runId: string,
  options: UseRunStreamOptions = {},
): UseRunStreamResult {
  const { token, baseUrl, fetchImpl, initialEvents, enabled = true } = options;

  const [events, setEvents] = useState<readonly AgentEvent[]>(
    () => initialEvents ?? [],
  );

  // CONNECTION IDENTITY, NOT A SYNCHRONOUS RESET. React 19 forbids calling
  // setState synchronously inside an effect (`react-hooks/set-state-in-effect`)
  // because it cascades renders. So the phase is stamped with the connection it
  // belongs to, and a phase from a previous connection is simply ignored during
  // render rather than cleared by a setState on mount. Same effect, no cascade.
  const connectionKey = `${runId}|${token ?? ""}|${baseUrl ?? ""}|${enabled}`;
  const [phase, setPhase] = useState<{
    key: string;
    status: RunStreamStatus;
    error?: AgentEventStreamError;
    closeReason?: AgentEventStreamCloseReason;
  } | null>(null);
  const current = phase?.key === connectionKey ? phase : null;

  // The reducer is idempotent by sequence number, so appending a replayed
  // prefix after a reconnect is safe and needs no de-duplication here. Doing it
  // in both places would be two implementations of one invariant.
  const appendEvent = useCallback((event: AgentEvent) => {
    setEvents((previous) => [...previous, event]);
  }, []);

  useEffect(() => {
    if (!enabled || !token || !runId) return;

    const stream = openAgentEventStream(
      { runId, token, baseUrl, fetchImpl },
      {
        onEvent: (event) => {
          setPhase({ key: connectionKey, status: "open" });
          appendEvent(event);
        },
        onError: (error, context) => {
          // `willRetry` is the client's own decision, and it is the only honest
          // source for this: a 401 or 404 never retries however many attempts
          // remain, so inferring "reconnecting" from the attempt count would
          // show a spinner over a dead stream.
          setPhase({
            key: connectionKey,
            status: context.willRetry ? "reconnecting" : "closed",
            error,
          });
        },
        onClose: (reason) => {
          setPhase((previous) => ({
            key: connectionKey,
            status: "closed",
            error: previous?.key === connectionKey ? previous.error : undefined,
            closeReason: reason,
          }));
        },
      },
    );

    return () => stream.abort();
  }, [runId, token, baseUrl, fetchImpl, enabled, appendEvent, connectionKey]);

  const view = useMemo(() => reduceRunView(events), [events]);

  const streamStatus: RunStreamStatus =
    !enabled || !token || !runId ? "idle" : (current?.status ?? "connecting");

  return {
    view,
    streamStatus,
    streamError: current?.error,
    closeReason: current?.closeReason,
    lastSequence: view.lastSequence,
  };
}

/**
 * The same derivation without a connection, for a finished run.
 *
 * A completed run reopens with every stage frozen, and it gets that for free
 * because the replay endpoint serves a finished run's events the same way it
 * serves a live one's -- so the view is a fold over the same list either way.
 */
export function runViewFromEvents(events: readonly AgentEvent[]): RunViewState {
  return reduceRunView(events);
}
