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
 * A fixed wall-clock anchor for every replay-journey test, so a run today, next
 * month and next year all see the same instant — the "deterministic across ten
 * consecutive runs" bar.
 *
 * CORRECTED 2026-09-10. This block used to state that `expires_at` is
 * "absolute, never rebased", and justified the pin as protection against the
 * offer expiring once real time passed the capture date. That was true when it
 * was written and stopped being true at #1764: `rebaseTemporalFields` now
 * shifts every nested temporal field, not just the envelope `timestamp`, so
 * `expires_at` moves with the series. Measured against the current capture,
 * `getReplayInitialEvents(Date.now())` puts it 11 hours in the FUTURE.
 *
 * The stale claim was not harmless — it read as a live production defect
 * ("real visitors will see a permanently-expired offer in production"), and was
 * one step from being filed as one. It is not a defect; #1764 fixed it.
 *
 * The pin stays, for determinism rather than for expiry. It must sit inside the
 * captured offer's validity window, which `e2e-fixture-transcription.test.ts`
 * asserts against the capture rather than trusting this comment.
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
