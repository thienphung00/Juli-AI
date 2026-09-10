import { beforeEach, describe, expect, it } from "vitest";

import {
  REPLAY_DECISION_STORAGE_KEY,
  clearReplayDecision,
  readReplayDecision,
  writeReplayDecision,
} from "../replay-decision";

describe("replay-decision", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("defaults to null when nothing has been decided", () => {
    expect(readReplayDecision()).toBeNull();
  });

  it("persists an approve decision under a dedicated storage key", () => {
    writeReplayDecision("run-123", "approve", Date.parse("2026-09-09T10:00:00.000Z"));

    const raw = window.sessionStorage.getItem(REPLAY_DECISION_STORAGE_KEY);
    expect(raw).not.toBeNull();
    expect(readReplayDecision()).toEqual({
      runId: "run-123",
      decision: "approve",
      decidedAt: "2026-09-09T10:00:00.000Z",
    });
  });

  it("persists a decline decision the same way", () => {
    writeReplayDecision("run-456", "decline", Date.parse("2026-09-09T11:00:00.000Z"));

    expect(readReplayDecision()).toEqual({
      runId: "run-456",
      decision: "decline",
      decidedAt: "2026-09-09T11:00:00.000Z",
    });
  });

  it("stores only runId, decision, and decidedAt — never the run itself", () => {
    writeReplayDecision("run-789", "approve", Date.parse("2026-09-09T12:00:00.000Z"));

    const raw = window.sessionStorage.getItem(REPLAY_DECISION_STORAGE_KEY);
    const parsed = JSON.parse(raw as string);
    expect(Object.keys(parsed).sort()).toEqual(["decidedAt", "decision", "runId"]);
  });

  it("clearReplayDecision removes the record", () => {
    writeReplayDecision("run-123", "approve");
    expect(readReplayDecision()).not.toBeNull();

    clearReplayDecision();

    expect(readReplayDecision()).toBeNull();
  });

  it("ignores a malformed stored value rather than crashing or trusting it blindly", () => {
    window.sessionStorage.setItem(REPLAY_DECISION_STORAGE_KEY, "not json");
    expect(readReplayDecision()).toBeNull();

    window.sessionStorage.setItem(
      REPLAY_DECISION_STORAGE_KEY,
      JSON.stringify({ runId: "run-1", decision: "maybe", decidedAt: "x" }),
    );
    expect(readReplayDecision()).toBeNull();

    window.sessionStorage.setItem(
      REPLAY_DECISION_STORAGE_KEY,
      JSON.stringify({ decision: "approve" }),
    );
    expect(readReplayDecision()).toBeNull();
  });

  it("never shares its storage key with entry-mode, demo-mode, or mutable-state keys", () => {
    expect(REPLAY_DECISION_STORAGE_KEY).not.toBe("juli_demo_entry_mode");
    expect(REPLAY_DECISION_STORAGE_KEY).not.toBe("juli_demo_mode");
    expect(REPLAY_DECISION_STORAGE_KEY).not.toBe("juli_demo_mutable_state");
  });

  it("uses sessionStorage, never localStorage", () => {
    writeReplayDecision("run-123", "approve");

    expect(window.localStorage.getItem(REPLAY_DECISION_STORAGE_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(REPLAY_DECISION_STORAGE_KEY)).not.toBeNull();
  });
});
