/**
 * Raw-event lookups for stage content (issue #1316, PUI-DESIGN.md §2).
 *
 * `RunViewState` (the reducer's output, #1315) deliberately carries only
 * *sequence numbers* per stage (`RunStageState.eventSequences`), never the
 * event payloads themselves -- the reducer's job is progression, not
 * content. The stage canvas still needs the actual payload (a tool's
 * `summary`, an approval request's `proposed_change`) to render "what the
 * events said," so this module looks those up directly from the raw event
 * list by sequence number. It computes nothing the events did not already
 * say: every field returned here is copied verbatim from a payload already
 * validated by `@juli/contracts`.
 */

import type { AgentEvent, WorkflowApprovalRequiredPayload } from "@juli/contracts";
import type { RunStageState } from "./reduce-run-view";

export type StageToolActivityStatus = "running" | "completed" | "failed";

export interface StageToolActivityItem {
  readonly toolCallId: string;
  readonly toolName: string;
  readonly status: StageToolActivityStatus;
  /** Verbatim `tool.completed` payload text -- undefined while still running. */
  readonly summary?: string;
}

/**
 * The tool-call activity that touched one stage, in the order those calls
 * were first observed, each merged from its `tool.started`/`tool.completed`
 * pair. A call seen only as `started` (still running, or the stream ended
 * before it completed) surfaces with `status: "running"` and no summary --
 * never invented text standing in for a result that has not arrived.
 */
export function toolActivityForStage(
  events: readonly AgentEvent[],
  stage: RunStageState,
): StageToolActivityItem[] {
  const bySequence = new Map<number, AgentEvent>(events.map((e) => [e.sequence_number, e]));
  const order: string[] = [];
  const byCallId = new Map<string, StageToolActivityItem>();

  for (const sequenceNumber of stage.eventSequences) {
    const event = bySequence.get(sequenceNumber);
    if (!event) continue;

    if (event.event_type === "tool.started") {
      if (!byCallId.has(event.payload.tool_call_id)) order.push(event.payload.tool_call_id);
      byCallId.set(event.payload.tool_call_id, {
        toolCallId: event.payload.tool_call_id,
        toolName: event.payload.tool_name,
        status: "running",
      });
    }

    if (event.event_type === "tool.completed") {
      if (!byCallId.has(event.payload.tool_call_id)) order.push(event.payload.tool_call_id);
      byCallId.set(event.payload.tool_call_id, {
        toolCallId: event.payload.tool_call_id,
        toolName: event.payload.tool_name,
        status: event.payload.ok ? "completed" : "failed",
        summary: event.payload.summary,
      });
    }
  }

  return order.map((toolCallId) => byCallId.get(toolCallId)!);
}

/**
 * The most recent `workflow.approval_required` event in the whole run, read
 * directly from raw events rather than `view.decisionRequest` -- which the
 * reducer clears once `workflow.completed`/`workflow.failed` fires (issue
 * #1315). The Cập nhật stage ("selected option as header," PUI-DESIGN.md
 * §2 row 5) still needs to show what was proposed even after the run has
 * finished and the decision is no longer "outstanding," so it reads the
 * historical event instead of the live decision-pending state.
 */
export function lastApprovalRequiredEvent(
  events: readonly AgentEvent[],
): (AgentEvent & { event_type: "workflow.approval_required" }) | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (event.event_type === "workflow.approval_required") {
      return event as AgentEvent & { event_type: "workflow.approval_required" };
    }
  }
  return null;
}

/** The `workflow.started` event's payload, read once from raw events -- the
 *  source of the workflow key used to look up the run's display title, and
 *  of `product_ref` (not currently rendered directly, but kept alongside so
 *  a future slice does not have to re-derive this lookup). */
export function workflowStartedPayload(
  events: readonly AgentEvent[],
): { workflow_key: string; product_ref: string; prompt_version: string } | null {
  const started = events.find((e) => e.event_type === "workflow.started");
  return started && started.event_type === "workflow.started" ? started.payload : null;
}

export type { WorkflowApprovalRequiredPayload };
