/**
 * Derives the run-ledger's `WorkflowRunListItem` for a decided replay run
 * (issue #1836, ADR-084 decision 6: "card consumption is rendered, not
 * hidden"). Same shape issue #1752 already seeded the staged run view
 * with -- every field computed from the captured golden scenario
 * (`replay-scenario.ts`) plus the one thing `replay-decision.ts` remembers
 * (the decision itself), never a second, hand-authored source.
 *
 * `created_at` / `completed_at` / `running_seconds_elapsed` are the
 * captured scenario's OWN rebased timestamps and their own recorded delta
 * -- `getReplayInitialEvents`/`getReplayContinuationEvents` already do the
 * rebasing (mirroring the server's own algorithm); this module never
 * recomputes a timestamp itself, only reads the ones those functions
 * already produced, anchored at the moment the seller actually decided
 * (`record.decidedAt`) -- the one real-world instant this whole derivation
 * has to work from.
 */
import type { AgentEvent, WorkflowRunListItem } from "@juli/contracts";

import type { ReplayDecisionRecord } from "../replay-decision";
import {
  REPLAY_SCENARIO_PRODUCT_NAME,
  getReplayContinuationEvents,
  getReplayInitialEvents,
} from "./replay-scenario";

/**
 * A decided replay run's continuation always ends in `workflow.completed`
 * (never `workflow.failed`) -- the captured scenario's own contract, for
 * both Đề xuất decisions: `stop_reason: "final_response"` (approve) and
 * `"confirmation_declined"` (decline). Per the server's own
 * `StopReason -> WorkflowRunStatus` table (`services/agent/status.py`)
 * both map to `WorkflowRunStatus.COMPLETED` -- not guessed here, it is the
 * only status this event type can honestly carry.
 */
const REPLAY_TERMINAL_STATUS: WorkflowRunListItem["status"] = "completed";

function findLastAssistantText(events: readonly AgentEvent[]): string | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.event_type === "assistant.text") {
      return event.payload.text;
    }
  }
  return null;
}

/**
 * Builds the ledger's `WorkflowRunListItem` for a decided replay run.
 * Throws if `record`'s captured continuation does not end in
 * `workflow.completed` -- a scenario contract violation this module must
 * surface loudly rather than render a run in an invented state.
 */
export function deriveReplayRunListItem(
  record: ReplayDecisionRecord,
): WorkflowRunListItem {
  const decidedAtMs = Date.parse(record.decidedAt);
  const initialEvents = getReplayInitialEvents(decidedAtMs);
  const continuationEvents = getReplayContinuationEvents(record.decision, decidedAtMs);

  const firstEvent = initialEvents[0];
  const terminalEvent = continuationEvents[continuationEvents.length - 1];

  if (!firstEvent || !terminalEvent || terminalEvent.event_type !== "workflow.completed") {
    throw new Error(
      `Replay decision "${record.decision}" for run "${record.runId}" does not ` +
        "resolve to a workflow.completed terminal event -- the captured " +
        "scenario's own contract.",
    );
  }

  const createdAt = firstEvent.timestamp;
  const completedAt = terminalEvent.timestamp;
  const runningSecondsElapsed = Math.max(
    0,
    Math.round((Date.parse(completedAt) - Date.parse(createdAt)) / 1000),
  );

  const allEvents: readonly AgentEvent[] = [...initialEvents, ...continuationEvents];

  return {
    id: record.runId,
    status: REPLAY_TERMINAL_STATUS,
    stop_reason: terminalEvent.payload.stop_reason,
    product_name: REPLAY_SCENARIO_PRODUCT_NAME,
    created_at: createdAt,
    completed_at: completedAt,
    running_seconds_elapsed: runningSecondsElapsed,
    latest_narration: findLastAssistantText(allEvents),
    decision_summary: null,
  };
}
