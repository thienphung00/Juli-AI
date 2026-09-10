/**
 * E2E-owned transcription of the captured golden scenario's own identifiers
 * (issue #1321, mirrors `src/lib/run-surface/replay-scenario.ts` and its
 * source fixture `src/lib/run-surface/golden-scenarios/
 * optimize_product_confirm_pause.json`) — same convention `workflow-
 * keys.ts` already uses for the Decisions fixtures: the e2e suite keeps its
 * own transcribed copy rather than importing app source into the test
 * runner, so a drift between the two is a visible diff in review, not a
 * silent shared-import coupling.
 */
export const REPLAY_SCENARIO_WORKFLOW_KEY = "optimize_product_2" as const;
export const REPLAY_SCENARIO_WORKFLOW_TITLE = "Tối ưu sản phẩm" as const;

/** The scenario's own captured `workflow_run_id` — the well-known replay
 *  run id `RunDetailRoute`'s replay branch matches against. */
export const REPLAY_SCENARIO_RUN_ID = "00000000-0000-0000-0000-00000000b453" as const;

export const REPLAY_SCENARIO_PRODUCT_NAME = "Áo thun cotton nam" as const;

/** The captured `workflow.approval_required` payload's one option
 *  (`option_id: "1"`) — the title it proposes, verbatim. */
export const REPLAY_SCENARIO_OPTION_ID = "1" as const;
export const REPLAY_SCENARIO_PROPOSED_TITLE = "Tiêu đề đã tối ưu" as const;

/**
 * A fixed wall-clock anchor for every replay-journey test — NOT a workaround
 * for "today happens to be past the capture date." `getReplayInitialEvents()`
 * rebases each event's own `timestamp` to `Date.now()` at mount, but the
 * nested `workflow.approval_required.expires_at` field is left as captured
 * (`2026-01-01T04:00:00Z`, absolute, never rebased) — verified
 * directly against a running build (issue #1321's own investigation). A
 * journey anchored to the real system clock would therefore silently start
 * failing the day real time crosses that fixed expiry, which is a latent
 * flakiness bomb the "deterministic across ten consecutive runs" bar is
 * meant to rule out, not just today's happenstance. Pinning `page.clock` to
 * a moment inside the captured scenario's own 4-hour validity window makes
 * every run — today, next month, next year — deterministic in exactly the
 * same way. Reported separately (not fixed here — production source is
 * outside this issue's file boundary): the SAME absolute-timestamp gap
 * means real visitors will see a permanently-expired offer in production
 * once real wall-clock time passes this date.
 */
export const REPLAY_SCENARIO_CLOCK_PIN = "2026-01-01T01:00:00.000Z" as const;

/** The confirmation POST route shape the client hits when a decision is
 *  submitted with a bearer token (`lib/run-surface/confirmation-client.ts`,
 *  `tool_call_id` from the captured event is `c2`). Never expected to be
 *  reached from the replay/anonymous door — ADR-094 decision 1 — so any
 *  request matching this pattern observed during the replay journey is
 *  itself a failure the journey asserts against. */
export const CONFIRMATION_DECISION_URL_PATTERN = new RegExp(
  `/v1/demo/runs/${REPLAY_SCENARIO_RUN_ID}/confirmations/`,
);
