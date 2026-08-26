/**
 * The seven honest, distinct terminal-state buckets the run ledger must
 * render (issue #1318 / W6-A/P-UI-5, PUI-DESIGN.md §4): completed,
 * completed-after-decline, cancelled, expired, timed out, failed, and
 * worker_lost. No two buckets ever share a label ("no state is dressed as
 * another").
 *
 * The mapping below is transcribed from the server's TOTAL
 * `StopReason -> WorkflowRunStatus` table
 * (`backend/src/juli_backend/services/agent/status.py::STOP_REASON_TO_STATUS`)
 * — this module reads `stop_reason` directly off the polled read model
 * (`GET /v1/demo/runs`, `WorkflowRunListItem.stop_reason`), never computes a
 * terminal state from timestamps or client-side inference. Two stop reasons
 * that the server maps to the SAME `WorkflowRunStatus` (`confirmation_declined`
 * and `final_response` both -> `completed`; `cancelled_by_seller` and
 * `confirmation_expired` both -> `cancelled`) are still split into distinct
 * seller-facing buckets here, because the seller-observable fact differs
 * even when the internal status column does not.
 */

/** The seven seller-facing terminal-state buckets, never a generic "done". */
export type RunTerminalStateKey =
  | "completed"
  | "completed_after_decline"
  | "cancelled"
  | "expired"
  | "timed_out"
  | "failed"
  | "worker_lost";

/**
 * Every `stop_reason` value the server's `StopReason` enum can produce
 * (`services/agent/status.py`), mapped to its seller-facing bucket. Kept as
 * a plain literal map (not an import from the Python enum, which this
 * package cannot reach) -- `__tests__/terminal-state.test.ts` cross-checks
 * this list stays exhaustive against a second, independently-transcribed
 * copy of the same enum.
 */
const STOP_REASON_TO_TERMINAL_STATE: Readonly<Record<string, RunTerminalStateKey>> =
  Object.freeze({
    final_response: "completed",
    confirmation_declined: "completed_after_decline",
    cancelled_by_seller: "cancelled",
    confirmation_expired: "expired",
    iteration_cap_exceeded: "timed_out",
    wall_clock_timeout: "timed_out",
    tool_error_unrecoverable: "failed",
    llm_error: "failed",
    concurrency_conflict: "failed",
    confirmation_diverged: "failed",
    output_validation_failed: "failed",
    worker_lost: "worker_lost",
  });

/**
 * Resolves a finished run's `stop_reason` (as returned verbatim by
 * `GET /v1/demo/runs`) into one of the seven seller-facing buckets.
 *
 * Returns `null` for a non-terminal run (`stop_reason` is `null` on the
 * wire for `queued` / `running` / `waiting_approval` runs) and for a
 * `stop_reason` this module does not recognize -- an unmapped value is a
 * defect to surface honestly (the caller falls back to a neutral "finished"
 * treatment), never guessed into one of the seven named buckets.
 */
export function resolveRunTerminalState(
  stopReason: string | null,
): RunTerminalStateKey | null {
  if (!stopReason) {
    return null;
  }
  return STOP_REASON_TO_TERMINAL_STATE[stopReason] ?? null;
}

/** Every `stop_reason` string this module maps -- exported for tests that
 *  want to iterate the full vocabulary rather than hand-pick a subset. */
export const KNOWN_STOP_REASONS: readonly string[] = Object.freeze(
  Object.keys(STOP_REASON_TO_TERMINAL_STATE),
);
