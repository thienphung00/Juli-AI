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
 * from `getReplayInitialEvents()` or `getReplayContinuationEvents()` (the
 * bundled scenario), never from a request.
 *
 * `resolveDecision` (issue #1764) is how the replay door's Đề xuất
 * decision advances the run: it appends the scenario's own captured
 * continuation for that decision onto the same paced-reveal queue the
 * initial events already use, rather than a caller inventing new events or
 * jumping the run straight to its terminal state. Idempotent -- a scenario
 * has exactly one decision to resolve, and a caller that (mis)fires twice
 * (e.g. a double click that slipped past the picker's own
 * `interactionDisabled` guard) must not append the continuation twice.
 */

import { useEffect, useRef, useState } from "react";
import type { AgentEvent } from "@juli/contracts";

import {
  getReplayContinuationEvents,
  getReplayInitialEvents,
  type ReplayDecisionKind,
} from "./replay-scenario";

export interface UseReplayEventsResult {
  readonly events: readonly AgentEvent[];
  readonly resolveDecision: (decision: ReplayDecisionKind) => void;
}

export function useReplayEvents(): UseReplayEventsResult {
  // Computed once per mount, not per render: recomputing on every render
  // would keep shifting "now" and the schedule out from under itself.
  const [scenario, setScenario] = useState<readonly AgentEvent[]>(() => getReplayInitialEvents());
  // The first event reveals immediately -- a seller who takes "Dùng thử
  // Demo" should never stare at a blank canvas waiting on a timer for the
  // run to even announce it started.
  const [revealedCount, setRevealedCount] = useState(() => (scenario.length > 0 ? 1 : 0));
  const decisionResolvedRef = useRef(false);

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

  function resolveDecision(decision: ReplayDecisionKind) {
    if (decisionResolvedRef.current) return;
    decisionResolvedRef.current = true;

    const continuation = getReplayContinuationEvents(decision);
    // Appended to the tail of the same array the reveal effect above is
    // already watching -- `revealedCount < scenario.length` goes true
    // again the instant this lands, so the continuation gets the exact
    // same one-at-a-time, delta-paced reveal the initial series gets,
    // never an instant dump.
    setScenario((previous) => [...previous, ...continuation]);
  }

  return { events: scenario.slice(0, revealedCount), resolveDecision };
}
