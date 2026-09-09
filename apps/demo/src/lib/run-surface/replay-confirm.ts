/**
 * The replay door's confirm handler (issue #1764, ADR-094 decision 1).
 *
 * `ReplayRunDetail` renders the same `RunStagedView` / `RunStageCanvas` /
 * `OptionPicker` chain the signed-in door does -- so it must supply the
 * same `ConfirmDecisionFn` shape those components already expect. Before
 * this module existed, `ReplayRunDetail` supplied none, so `OptionPicker`
 * fell through to its own default, `submitConfirmationDecision` --
 * a real, bearer-less `POST /v1/demo/runs/{run_id}/confirmations/
 * {tool_call_id}`, observed 404ing. This is the fix: a handler with the
 * identical shape that resolves the decision LOCALLY, from the scenario's
 * own captured continuation (`getReplayContinuationEvents`), and never
 * calls `fetch` at all.
 *
 * Depends only on `confirmation-decision.ts` (the neutral type contract),
 * `replay-scenario.ts` (the local continuation data), and
 * `replay-decision.ts` (a plain `sessionStorage` write, no network of any
 * kind) -- never on `confirmation-client.ts`, so this module's own
 * presence in the replay door's reachable module graph never pulls in
 * that file's network call site or its literal backend route path
 * (`replay-module-graph.test.ts`).
 *
 * ISSUE #1836: this is the one place a replay decision actually resolves,
 * so it is also the one place that decision gets recorded --
 * `writeReplayDecision` before `resolveDecision` reveals the outcome, so a
 * visitor who returns to Decisions mid-reveal already has the record.
 */

import type {
  ConfirmationDecisionResult,
  ConfirmDecisionFn,
} from "./confirmation-decision";
import type { ReplayDecisionKind } from "./replay-scenario";
import { writeReplayDecision } from "../replay-decision";

/**
 * Builds a `ConfirmDecisionFn` scoped to one replay run id.
 *
 * `resolveDecision` is `useReplayEvents()`'s own appender -- calling it is
 * what actually advances the run (appending the captured continuation onto
 * the paced-reveal queue); this function's own job is just to validate the
 * call matches the run this door is rendering and shape the
 * `ConfirmationDecisionResult` the picker expects back, exactly like the
 * real client's response does.
 */
export function buildReplayConfirm(
  replayRunId: string,
  resolveDecision: (decision: ReplayDecisionKind) => void,
): ConfirmDecisionFn {
  return async function replayConfirm(runId, _toolCallId, decision) {
    if (runId !== replayRunId) {
      throw new Error(
        `Replay confirm handler invoked for run "${runId}", but the replay ` +
          `door only ever renders the captured run "${replayRunId}".`,
      );
    }

    writeReplayDecision(runId, decision);
    resolveDecision(decision);

    const result: ConfirmationDecisionResult = {
      decision,
      status: decision === "approve" ? "confirmed" : "declined",
      // No real Celery task exists in the replay door -- this id is never
      // read by any caller (`OptionPicker.decide()` only branches on
      // `decision`), it exists purely so this value is honestly labeled
      // rather than a borrowed real-looking id.
      celeryTaskId: "replay-no-task",
    };
    return result;
  };
}
