import { describe, expect, it } from "vitest";

import { CARD_STATUS_LABELS } from "../../lib/quyet-dinh/card-model";
import type { QdRun } from "../../lib/quyet-dinh/p10-types";
import { listChip, runChip } from "../../lib/quyet-dinh/run-model";
import { SIMULATED_DONE_TEXT, SIMULATED_DONE_TITLE, SIMULATED_RUN_LABEL } from "../../lib/quyet-dinh/simulated-copy";
import { isExecutedRun } from "../quyet-dinh/do-luong-panel";

/**
 * P61-B (D71.2): a run whose writes went to Juli's test shop is never shown as a change on
 * the seller's shop ("Đã áp dụng"), its card says "Đã chạy thử", and it is not listed in
 * Đo lường.
 */

function completed(simulated: boolean | undefined): QdRun {
  return {
    id: "r1",
    status: "completed",
    stop_reason: "final_response",
    product_name: "Áo thun",
    created_at: "2026-10-20T00:00:00Z",
    completed_at: "2026-10-20T00:05:00Z",
    running_seconds_elapsed: 60,
    latest_narration: null,
    decision_summary: null,
    simulated,
  } as QdRun;
}

describe("P61-B — a simulated run says so", () => {
  it("the run and list chips say Đã chạy thử, never Đã áp dụng", () => {
    const run = completed(true);
    expect(runChip(run, "listing", "done")).toEqual({ label: SIMULATED_RUN_LABEL, tone: "muted" });
    expect(runChip(run, "photo", "done").label).toBe(SIMULATED_RUN_LABEL);
    expect(listChip(run).label).toBe(SIMULATED_RUN_LABEL);
    // A revert keeps its own label.
    expect(runChip(run, "revert", "done").label).toBe("Đã hoàn tác");
  });

  it("a run that really changed the shop still says Đã áp dụng", () => {
    for (const run of [completed(false), completed(undefined)]) {
      expect(runChip(run, "listing", "done").label).toBe("Đã áp dụng");
      expect(listChip(run).label).toBe("Đã áp dụng");
    }
  });

  it("the card label and the done copy never claim a change on the shop", () => {
    expect(CARD_STATUS_LABELS.simulated).toBe(SIMULATED_RUN_LABEL);
    for (const text of [SIMULATED_RUN_LABEL, SIMULATED_DONE_TITLE, SIMULATED_DONE_TEXT]) {
      expect(text).not.toMatch(/Đã áp dụng|đã cập nhật/i);
    }
    expect(SIMULATED_DONE_TITLE).toContain("chưa thay đổi");
  });

  it("a simulated run is not listed in Đo lường", () => {
    expect(isExecutedRun(completed(true))).toBe(false);
    expect(isExecutedRun(completed(false))).toBe(true);
    expect(isExecutedRun(completed(undefined))).toBe(true);
  });
});
