import { beforeEach, describe, expect, it, vi } from "vitest";

import { readReplayDecision } from "../../replay-decision";
import { buildReplayConfirm } from "../replay-confirm";

const REPLAY_RUN_ID = "run-abc-123";

describe("buildReplayConfirm — records the decision (issue #1836)", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("records an approve decision to sessionStorage when the confirm handler resolves", async () => {
    const resolveDecision = vi.fn();
    const confirm = buildReplayConfirm(REPLAY_RUN_ID, resolveDecision);

    await confirm(REPLAY_RUN_ID, "call-1", "approve", null);

    expect(readReplayDecision()).toMatchObject({
      runId: REPLAY_RUN_ID,
      decision: "approve",
    });
  });

  it("records a decline decision to sessionStorage when the confirm handler resolves", async () => {
    const resolveDecision = vi.fn();
    const confirm = buildReplayConfirm(REPLAY_RUN_ID, resolveDecision);

    await confirm(REPLAY_RUN_ID, "call-1", "decline", null);

    expect(readReplayDecision()).toMatchObject({
      runId: REPLAY_RUN_ID,
      decision: "decline",
    });
  });

  it("still resolves the decision locally via resolveDecision -- recording does not replace advancing the run", async () => {
    const resolveDecision = vi.fn();
    const confirm = buildReplayConfirm(REPLAY_RUN_ID, resolveDecision);

    await confirm(REPLAY_RUN_ID, "call-1", "approve", null);

    expect(resolveDecision).toHaveBeenCalledWith("approve");
  });

  it("never records a decision for a mismatched run id -- the guard throws before recording", async () => {
    const resolveDecision = vi.fn();
    const confirm = buildReplayConfirm(REPLAY_RUN_ID, resolveDecision);

    await expect(confirm("some-other-run", "call-1", "approve", null)).rejects.toThrow();

    expect(readReplayDecision()).toBeNull();
  });
});
