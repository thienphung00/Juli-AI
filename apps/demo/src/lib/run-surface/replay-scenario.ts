/**
 * The captured golden scenario, shipped as a client build artifact
 * (issue #1752, ADR-084 decision 2, ADR-094 decision 5).
 *
 * `golden-scenarios/optimize_product_confirm_pause.json` is a byte-for-byte
 * copy of `tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json`
 * -- the capture tool's own output. Nothing here reformats, trims, or
 * re-keys it; `__tests__/replay-scenario.test.ts` asserts the raw bytes
 * still match the fixture, so a hand-edit on the way into the bundle fails
 * CI (ADR-084 d.2 bans hand-authored event JSON everywhere in this
 * pipeline).
 *
 * IMPORTED, NOT FETCHED. A static `import` of the JSON module is bundled
 * into the built JS by webpack at compile time -- present in the built
 * artifact by construction, checked by `scripts/verify-replay-scenario-in-
 * build.mjs` (run as part of `next build`). A network call here would also
 * trip `src/__tests__/replay-module-graph.test.ts`'s "no network call site
 * reachable from the replay entry" assertion, and would need a round trip
 * the replay path must never make. (Spelled out without the literal call
 * syntax on purpose -- that exact text once matched the very regex this
 * paragraph describes, the first time this file entered that test's
 * reachable graph, issue #1772.)
 *
 * TIMESTAMP REBASING mirrors the server's own algorithm exactly
 * (`backend/.../golden_scenarios/replay.py::seed_replay_run`): delta from
 * the first event is preserved, the whole series is shifted to start at
 * `now`. Same algorithm, ported rather than shared, because the source
 * languages differ -- a dual-language contract test would be the next
 * layer of drift protection if a second scenario needed one; one scenario
 * does not yet justify it.
 */

import type { AgentEvent } from "@juli/contracts";
import { validateAgentEvent } from "@juli/contracts";

import scenario from "./golden-scenarios/optimize_product_confirm_pause.json";

interface RawGoldenEvent {
  readonly workflow_run_id: string;
  readonly sequence_number: number;
  readonly event_type: string;
  readonly timestamp: string;
  readonly payload: Record<string, unknown>;
  readonly v: number;
}

interface GoldenScenarioFile {
  readonly scenario_id: string;
  readonly workflow_key: string;
  readonly prompt_sha256: string;
  readonly captured_at: string;
  readonly events: readonly RawGoldenEvent[];
  readonly continuations: Readonly<Record<string, readonly RawGoldenEvent[]>>;
}

const REPLAY_SCENARIO = scenario as GoldenScenarioFile;

// Absence must fail loudly, never render an empty run (issue #1752's own
// acceptance criterion). A scenario file present but empty of events is the
// same failure mode as a scenario file missing entirely -- both are caught
// here, at module load, rather than surfacing as a run that silently never
// advances.
if (!REPLAY_SCENARIO.events || REPLAY_SCENARIO.events.length === 0) {
  throw new Error(
    "Replay scenario 'optimize_product_confirm_pause' has no events -- " +
      "the captured fixture must ship non-empty. A missing or empty " +
      "scenario must fail loudly, never render an idle run.",
  );
}

/**
 * The well-known replay run id -- the scenario's own captured
 * `workflow_run_id`, not a value invented here. Matches the UUID already
 * pinned in `run-detail-route.test.tsx` and
 * `in-progress-detail-route-dispatch.test.tsx`.
 */
export const REPLAY_SCENARIO_RUN_ID: string = REPLAY_SCENARIO.events[0].workflow_run_id;

/** Illustrative sample-data copy, not event content -- ADR-084 d.2's ban is
 *  on hand-authored *event* JSON, not on UI display strings. Reuses the
 *  sample product name already used throughout the run-surface fixtures
 *  (`run-detail-route.test.tsx`, `run-staged-view.test.tsx`, etc). */
export const REPLAY_SCENARIO_PRODUCT_NAME = "Áo thun cotton nam";

function rebaseEvent(event: RawGoldenEvent, deltaMs: number, nowMs: number): AgentEvent {
  const rebased = {
    ...event,
    timestamp: new Date(nowMs + deltaMs).toISOString(),
  };

  return validateAgentEvent(rebased);
}

/**
 * The scenario's events, timestamps rebased to `nowMs` (default: the
 * moment of the call) with recorded inter-event deltas preserved exactly
 * -- so the replay paces like a real run rather than arriving all at once
 * (ADR-084 decision 2).
 */
export function getReplayInitialEvents(nowMs: number = Date.now()): readonly AgentEvent[] {
  const firstTimestampMs = Date.parse(REPLAY_SCENARIO.events[0].timestamp);

  return REPLAY_SCENARIO.events.map((event) =>
    rebaseEvent(event, Date.parse(event.timestamp) - firstTimestampMs, nowMs),
  );
}
