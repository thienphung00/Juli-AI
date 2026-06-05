import type { PersonaId, WorkflowId } from "@/lib/mock-data/seller-personas/schemas";
import { getUxSessionId } from "./session";
import type { TaskUxEventName, TaskUxEventPayload } from "./types";

export interface TrackTaskUxInput {
  workflow: WorkflowId;
  task_type: string;
  persona_id: PersonaId;
}

function buildPayload(
  event: TaskUxEventName,
  input: TrackTaskUxInput,
): TaskUxEventPayload {
  return {
    event,
    workflow: input.workflow,
    task_type: input.task_type,
    persona_id: input.persona_id,
    session_id: getUxSessionId(),
    timestamp: new Date().toISOString(),
  };
}

/** Fail-silent analytics sink — never throws to callers (issue #122). */
export function emitTaskUxEvent(
  event: TaskUxEventName,
  input: TrackTaskUxInput,
): void {
  if (typeof window === "undefined") return;

  try {
    const detail = buildPayload(event, input);

    window.dispatchEvent(
      new CustomEvent("juli:analytics", { detail }),
    );

    if (process.env.NODE_ENV === "development") {
      console.info(event, detail);
    }
  } catch {
    // Analytics must never break seller UX.
  }
}

export function trackTaskClicked(input: TrackTaskUxInput): void {
  emitTaskUxEvent("task_clicked", input);
}

export function trackTaskApproved(input: TrackTaskUxInput): void {
  emitTaskUxEvent("task_approved", input);
}

export function trackTaskDismissed(input: TrackTaskUxInput): void {
  emitTaskUxEvent("task_dismissed", input);
}
