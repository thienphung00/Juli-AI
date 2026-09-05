import { describe, expect, it } from "vitest";

import {
  KNOWN_STOP_REASONS,
  resolveRunTerminalState,
  type RunTerminalStateKey,
} from "../terminal-state";

// Independently transcribed from
// `backend/src/juli_backend/services/agent/status.py::StopReason` /
// `STOP_REASON_TO_STATUS` -- deliberately NOT imported from the module
// under test, so a regression that silently drops a stop_reason from the
// map is caught here rather than trivially agreeing with itself.
const EXPECTED_STOP_REASON_BUCKETS: Record<string, RunTerminalStateKey> = {
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
};

describe("resolveRunTerminalState", () => {
  it("returns null for a non-terminal run (null stop_reason)", () => {
    expect(resolveRunTerminalState(null)).toBeNull();
  });

  it.each(Object.entries(EXPECTED_STOP_REASON_BUCKETS))(
    "maps stop_reason=%s to bucket %s",
    (stopReason, expectedBucket) => {
      expect(resolveRunTerminalState(stopReason)).toBe(expectedBucket);
    },
  );

  it("is exhaustive over every known stop_reason value", () => {
    expect(new Set(KNOWN_STOP_REASONS)).toEqual(
      new Set(Object.keys(EXPECTED_STOP_REASON_BUCKETS)),
    );
  });

  it("splits stop reasons that share a server-side WorkflowRunStatus into distinct seller-facing buckets", () => {
    // final_response and confirmation_declined both map to WorkflowRunStatus
    // .COMPLETED server-side, but must render as different seller facts.
    expect(resolveRunTerminalState("final_response")).not.toBe(
      resolveRunTerminalState("confirmation_declined"),
    );
    // cancelled_by_seller and confirmation_expired both map to
    // WorkflowRunStatus.CANCELLED server-side, same requirement.
    expect(resolveRunTerminalState("cancelled_by_seller")).not.toBe(
      resolveRunTerminalState("confirmation_expired"),
    );
  });

  it("returns null (never a fabricated bucket) for an unrecognized stop_reason", () => {
    expect(resolveRunTerminalState("some_future_reason_not_yet_mapped")).toBeNull();
  });

  it("produces exactly seven distinct terminal-state buckets across the full vocabulary", () => {
    const buckets = new Set(
      KNOWN_STOP_REASONS.map((reason) => resolveRunTerminalState(reason)),
    );
    expect(buckets.size).toBe(7);
  });
});
