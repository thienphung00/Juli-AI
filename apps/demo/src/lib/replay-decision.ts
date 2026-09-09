/**
 * Replay decision record — `sessionStorage`, alongside `entry-mode.ts`'s
 * `juli_demo_entry_mode` (issue #1319) and with the same lifetime (issue
 * #1836, ADR-084 decision 6, ADR-094 decision 1).
 *
 * Deliberately its own storage key, independent of `demo-state.tsx`'s
 * `juli_demo_mode`/`juli_demo_mutable_state` — same reasoning as
 * `entry-mode.ts`'s own docstring: a concurrent slice owns that key, and
 * this record answers a narrower question ("did the one replayed run get
 * decided, and how") that key was never shaped to hold.
 *
 * Stores the MINIMUM: which captured run was decided, what the decision
 * was, and when. Never the run itself — every other `WorkflowRunListItem`
 * field is derived from the captured scenario at read time
 * (`run-surface/replay-ledger-item.ts`), so there is exactly one source of
 * truth for the run's shape and this record can never disagree with it.
 *
 * `sessionStorage`, never `localStorage`: a decision that survived a tab
 * close would mean the next visitor on that browser opens the demo with
 * the recommendation already missing — worse than the behaviour this
 * record exists to fix. `sessionStorage` is also not a database row, so
 * ADR-094 decision 1 ("client replay with no persistence") holds without
 * amendment.
 */
export const REPLAY_DECISION_STORAGE_KEY = "juli_demo_replay_decision";

/** Structurally identical to `run-surface/replay-scenario.ts`'s own
 *  `ReplayDecisionKind` — named separately here (rather than imported) so
 *  this module stays as self-contained as `entry-mode.ts` is, per that
 *  file's own docstring. The two types are freely assignable to each other
 *  because both are exactly `"approve" | "decline"`. */
export type ReplayDecisionOutcome = "approve" | "decline";

export interface ReplayDecisionRecord {
  readonly runId: string;
  readonly decision: ReplayDecisionOutcome;
  readonly decidedAt: string;
}

function isReplayDecisionOutcome(value: unknown): value is ReplayDecisionOutcome {
  return value === "approve" || value === "decline";
}

/**
 * Reads the recorded decision, or `null` when nothing has been decided yet,
 * the tab session never held one, or the stored value is malformed. A
 * malformed record must never crash the read — it is treated exactly like
 * "nothing decided", the same fail-safe stance `entry-mode.ts` takes on an
 * unrecognized stored value.
 */
export function readReplayDecision(): ReplayDecisionRecord | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.sessionStorage.getItem(REPLAY_DECISION_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  let parsed: Partial<ReplayDecisionRecord>;
  try {
    parsed = JSON.parse(raw) as Partial<ReplayDecisionRecord>;
  } catch {
    return null;
  }

  if (
    typeof parsed.runId === "string" &&
    parsed.runId.length > 0 &&
    isReplayDecisionOutcome(parsed.decision) &&
    typeof parsed.decidedAt === "string" &&
    parsed.decidedAt.length > 0
  ) {
    return { runId: parsed.runId, decision: parsed.decision, decidedAt: parsed.decidedAt };
  }

  return null;
}

/**
 * Records that `runId` was decided `decision`, at the moment of the call
 * (or `decidedAtMs`, injectable for tests). Overwrites any prior record —
 * the captured scenario has exactly one decision to resolve, so there is
 * never more than one record to hold.
 */
export function writeReplayDecision(
  runId: string,
  decision: ReplayDecisionOutcome,
  decidedAtMs: number = Date.now(),
): void {
  if (typeof window === "undefined") {
    return;
  }

  const record: ReplayDecisionRecord = {
    runId,
    decision,
    decidedAt: new Date(decidedAtMs).toISOString(),
  };
  window.sessionStorage.setItem(REPLAY_DECISION_STORAGE_KEY, JSON.stringify(record));
}

/**
 * Clears the recorded decision — `resetMockState()`'s own job (issue
 * #1836): "Làm mới Demo" must put the demo back, and a decided replay run
 * left behind after a refresh is exactly the failure this issue exists to
 * fix in the other direction.
 */
export function clearReplayDecision(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(REPLAY_DECISION_STORAGE_KEY);
}
