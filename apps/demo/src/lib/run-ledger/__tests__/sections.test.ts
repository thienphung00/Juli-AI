import { describe, expect, it } from "vitest";

import { groupRunsIntoLedgerSections } from "../sections";
import { buildRunListItem } from "./fixtures";

describe("groupRunsIntoLedgerSections", () => {
  it("sorts a waiting_approval run into waitingOnYou", () => {
    const run = buildRunListItem({ id: "run-1", status: "waiting_approval" });
    const sections = groupRunsIntoLedgerSections([run]);

    expect(sections.waitingOnYou).toEqual([run]);
    expect(sections.running).toEqual([]);
    expect(sections.finished).toEqual([]);
  });

  it("sorts a queued run (zero events) into running -- proving the ledger reads the polled list, not the event stream", () => {
    const run = buildRunListItem({
      id: "run-queued",
      status: "queued",
      latest_narration: null,
    });
    const sections = groupRunsIntoLedgerSections([run]);

    expect(sections.running).toEqual([run]);
  });

  it("sorts a running run into running", () => {
    const run = buildRunListItem({ id: "run-2", status: "running" });
    expect(groupRunsIntoLedgerSections([run]).running).toEqual([run]);
  });

  it.each(["completed", "cancelled", "timed_out", "failed"])(
    "sorts a %s run into finished",
    (status) => {
      const run = buildRunListItem({ id: `run-${status}`, status });
      expect(groupRunsIntoLedgerSections([run]).finished).toEqual([run]);
    },
  );

  it("preserves the server's own order within each section rather than re-sorting", () => {
    const first = buildRunListItem({ id: "r1", status: "running", created_at: "2026-08-25T09:00:00.000Z" });
    const second = buildRunListItem({ id: "r2", status: "running", created_at: "2026-08-25T08:00:00.000Z" });

    const sections = groupRunsIntoLedgerSections([first, second]);

    expect(sections.running.map((r) => r.id)).toEqual(["r1", "r2"]);
  });

  it("partitions a mixed list into all three sections simultaneously", () => {
    const waiting = buildRunListItem({ id: "w1", status: "waiting_approval" });
    const running = buildRunListItem({ id: "run1", status: "running" });
    const queued = buildRunListItem({ id: "q1", status: "queued" });
    const finished = buildRunListItem({ id: "f1", status: "completed", stop_reason: "final_response" });

    const sections = groupRunsIntoLedgerSections([finished, queued, waiting, running]);

    expect(sections.waitingOnYou.map((r) => r.id)).toEqual(["w1"]);
    expect(sections.running.map((r) => r.id)).toEqual(["q1", "run1"]);
    expect(sections.finished.map((r) => r.id)).toEqual(["f1"]);
  });
});
