import { describe, expect, it } from "vitest";

import type { ReplayDecisionRecord } from "../../replay-decision";
import { deriveReplayRunListItem } from "../replay-ledger-item";
import { REPLAY_SCENARIO_PRODUCT_NAME, REPLAY_SCENARIO_RUN_ID } from "../replay-scenario";

function buildRecord(
  overrides: Partial<ReplayDecisionRecord> = {},
): ReplayDecisionRecord {
  return {
    runId: REPLAY_SCENARIO_RUN_ID,
    decision: "approve",
    decidedAt: "2026-09-09T10:00:00.000Z",
    ...overrides,
  };
}

describe("deriveReplayRunListItem", () => {
  it("derives id from the captured run id, never invented", () => {
    const item = deriveReplayRunListItem(buildRecord());
    expect(item.id).toBe(REPLAY_SCENARIO_RUN_ID);
  });

  it("derives product_name from the captured scenario's own sample", () => {
    const item = deriveReplayRunListItem(buildRecord());
    expect(item.product_name).toBe(REPLAY_SCENARIO_PRODUCT_NAME);
  });

  it("approve resolves to status completed with stop_reason final_response", () => {
    const item = deriveReplayRunListItem(buildRecord({ decision: "approve" }));
    expect(item.status).toBe("completed");
    expect(item.stop_reason).toBe("final_response");
  });

  it("decline resolves to status completed with stop_reason confirmation_declined -- a choice, never an error", () => {
    const item = deriveReplayRunListItem(buildRecord({ decision: "decline" }));
    expect(item.status).toBe("completed");
    expect(item.stop_reason).toBe("confirmation_declined");
  });

  it("decision_summary is null once decided", () => {
    const item = deriveReplayRunListItem(buildRecord());
    expect(item.decision_summary).toBeNull();
  });

  it("latest_narration is null -- this scenario carries no assistant.text event", () => {
    const item = deriveReplayRunListItem(buildRecord());
    expect(item.latest_narration).toBeNull();
  });

  it("created_at and completed_at are real, distinct-from-each-other-capable ISO timestamps, with completed_at not before created_at", () => {
    const item = deriveReplayRunListItem(buildRecord());
    expect(new Date(item.created_at).toString()).not.toBe("Invalid Date");
    expect(item.completed_at).not.toBeNull();
    expect(new Date(item.completed_at as string).toString()).not.toBe("Invalid Date");
    expect(Date.parse(item.completed_at as string)).toBeGreaterThanOrEqual(
      Date.parse(item.created_at),
    );
  });

  it("running_seconds_elapsed is a non-negative number derived from the captured deltas", () => {
    const item = deriveReplayRunListItem(buildRecord());
    expect(item.running_seconds_elapsed).toBeGreaterThanOrEqual(0);
    expect(Number.isFinite(item.running_seconds_elapsed)).toBe(true);
  });

  it("is a pure function of the record -- calling it twice for the same record yields the same terminal fields", () => {
    const record = buildRecord();
    const first = deriveReplayRunListItem(record);
    const second = deriveReplayRunListItem(record);
    expect(second.status).toBe(first.status);
    expect(second.stop_reason).toBe(first.stop_reason);
    expect(second.id).toBe(first.id);
    expect(second.product_name).toBe(first.product_name);
  });
});
