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
 * reachable from the replay entry" assertion, and would need a network
 * round trip the replay path must never make.
 *
 * TIMESTAMP REBASING mirrors the server's own algorithm exactly
 * (`backend/.../golden_scenarios/replay.py::seed_replay_run`): delta from
 * the first event is preserved, the whole series is shifted to start at
 * `now`. Same algorithm, ported rather than shared, because the source
 * languages differ -- a dual-language contract test would be the next
 * layer of drift protection if a second scenario needed one; one scenario
 * does not yet justify it.
 *
 * NESTED TEMPORAL FIELDS ARE REBASED TOO (issue #1764). The envelope
 * `timestamp` is not the only wall-clock value a captured event carries --
 * `workflow.approval_required`'s payload has its own `expires_at`, captured
 * at record time, that a byte-identical, envelope-only rebase left stale:
 * shipped once, the offer was already expired for every visitor from the
 * moment "now" passed the capture's own expiry window. `rebaseTemporalFields`
 * below walks every string reachable from an event (envelope AND payload,
 * recursively, arrays included) and shifts any that parse as an ISO-8601
 * timestamp by the SAME constant shift the envelope timestamp gets --
 * general on purpose, so the next captured scenario that carries a nested
 * timestamp under a field name this file has never heard of is rebased
 * correctly the first time, not just after it, too, ships already expired.
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

export type ReplayDecisionKind = "approve" | "decline";

// Deliberately strict: a quote-delimited full ISO-8601 date-time, optionally
// fractional-second, optionally zone-suffixed. Anchored start-to-end so it
// never matches a substring inside a longer, unrelated string (a UUID, a
// params_sha hex digest, a Vietnamese title) -- only a value that is
// ENTIRELY a timestamp gets rebased.
const ISO_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/;

function isRebasableTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    ISO_TIMESTAMP_PATTERN.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

/**
 * Walks `value` recursively (objects, arrays, and scalars alike) and shifts
 * every ISO-8601 timestamp string it finds by `shiftMs` -- the envelope
 * `timestamp` and any nested field (`expires_at`, or whatever the next
 * scenario carries) are rebased identically, by construction, because
 * neither is special-cased: both are just strings this walk happens to
 * visit.
 */
function rebaseTemporalFields<T>(value: T, shiftMs: number): T {
  if (isRebasableTimestamp(value)) {
    return new Date(Date.parse(value) + shiftMs).toISOString() as unknown as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => rebaseTemporalFields(item, shiftMs)) as unknown as T;
  }
  if (value !== null && typeof value === "object") {
    const rebased: Record<string, unknown> = {};
    for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
      rebased[key] = rebaseTemporalFields(nested, shiftMs);
    }
    return rebased as T;
  }
  return value;
}

function rebaseEvent(event: RawGoldenEvent, shiftMs: number): AgentEvent {
  const rebased = rebaseTemporalFields(event as unknown as Record<string, unknown>, shiftMs);
  return validateAgentEvent(rebased);
}

/**
 * Rebases an ordered event series so it starts at `nowMs`, preserving both
 * the recorded inter-event deltas (ADR-084 decision 2) AND every nested
 * temporal field's offset from the series' own first event (issue #1764) --
 * one constant shift, applied uniformly by `rebaseTemporalFields`.
 */
function rebaseSeries(events: readonly RawGoldenEvent[], nowMs: number): readonly AgentEvent[] {
  const firstTimestampMs = Date.parse(events[0]!.timestamp);
  const shiftMs = nowMs - firstTimestampMs;
  return events.map((event) => rebaseEvent(event, shiftMs));
}

/**
 * The scenario's events, timestamps (envelope AND nested) rebased to
 * `nowMs` (default: the moment of the call) with recorded inter-event
 * deltas preserved exactly -- so the replay paces like a real run rather
 * than arriving all at once, and its Đề xuất offer is never already
 * expired the moment it is revealed (ADR-084 decision 2, issue #1764).
 */
export function getReplayInitialEvents(nowMs: number = Date.now()): readonly AgentEvent[] {
  return rebaseSeries(REPLAY_SCENARIO.events, nowMs);
}

/**
 * The scenario's captured continuation for a Đề xuất decision ("approve" or
 * "decline"), rebased the same way as `getReplayInitialEvents` -- its own
 * series, shifted to start at `nowMs` (default: the moment of the call,
 * i.e. the moment the seller actually decided) with its own recorded
 * inter-event deltas preserved. Used by the replay door's local confirm
 * handler (`replay-confirm.ts`) to resolve a decision without ever calling
 * the network (ADR-094 decision 1, ADR-084 decision 2, issue #1764).
 */
export function getReplayContinuationEvents(
  decision: ReplayDecisionKind,
  nowMs: number = Date.now(),
): readonly AgentEvent[] {
  const events = REPLAY_SCENARIO.continuations[decision];
  if (!events || events.length === 0) {
    throw new Error(
      `Replay scenario 'optimize_product_confirm_pause' has no captured ` +
        `continuation for decision "${decision}" -- the captured fixture ` +
        "must ship a non-empty continuation for both decisions.",
    );
  }
  return rebaseSeries(events, nowMs);
}
