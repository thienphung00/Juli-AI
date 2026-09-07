"use client";

/**
 * `useReplayEvents()` -- the client replay's own local pacing (issue #1752,
 * ADR-084 decision 2).
 *
 * `useRunStream`'s `initialEvents` seeds the whole array into state at
 * mount in one shot, by design: it exists for a *finished* run rendered
 * from already-fetched events (see its own module doc). The replay path
 * wants the opposite -- events revealed one at a time, spaced by their own
 * recorded inter-event deltas rebased to now, so the run paces like a live
 * one instead of arriving instantly. That is a second, small piece of
 * impurity (timers, not fetch), so it gets its own hook rather than
 * overloading `useRunStream`'s contract -- exactly the seam #1315's
 * pure/impure split already draws between `reduceRunView` and
 * `useRunStream`.
 *
 * NO TOKEN, NO FETCH, NO NETWORK. Every event this hook ever reveals came
 * from `getReplayInitialEvents()` (the bundled scenario), never from a
 * request.
 */

import { useEffect, useState } from "react";
import type { AgentEvent } from "@juli/contracts";

import { getReplayInitialEvents } from "./replay-scenario";

export interface UseReplayEventsResult {
  readonly events: readonly AgentEvent[];
}

export function useReplayEvents(): UseReplayEventsResult {
  // Computed once per mount, not per render: recomputing on every render
  // would keep shifting "now" and the schedule out from under itself.
  const [scenario] = useState(() => getReplayInitialEvents());
  // The first event reveals immediately -- a seller who takes "Dùng thử
  // Demo" should never stare at a blank canvas waiting on a timer for the
  // run to even announce it started.
  const [revealedCount, setRevealedCount] = useState(() => (scenario.length > 0 ? 1 : 0));

  useEffect(() => {
    if (revealedCount >= scenario.length) {
      return;
    }

    const nextEvent = scenario[revealedCount];
    const delayMs = Math.max(0, Date.parse(nextEvent.timestamp) - Date.now());

    const timer = window.setTimeout(() => {
      setRevealedCount((count) => count + 1);
    }, delayMs);

    return () => window.clearTimeout(timer);
  }, [revealedCount, scenario]);

  return { events: scenario.slice(0, revealedCount) };
}
