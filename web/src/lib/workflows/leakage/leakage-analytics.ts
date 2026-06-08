import type { LeakageTaskType } from "@/lib/mock-data/leakage-workflow";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { getUxSessionId } from "@/lib/ux-analytics/session";
import type { LeakageWorkflowStep } from "./state-machine";

export type LeakageUxEventName =
  | "leakage_workflow_started"
  | "leakage_step_completed"
  | "leakage_workflow_completed"
  | "task_dismissed_with_reason";

export interface LeakageUxEventPayload {
  event: LeakageUxEventName;
  workflow: "leakage";
  task_type: LeakageTaskType;
  persona_id: PersonaId;
  session_id: string;
  timestamp: string;
  step?: LeakageWorkflowStep;
  dismiss_reason?: string;
  dismiss_note?: string;
}

interface LeakageAnalyticsInput {
  personaId: PersonaId;
  taskType: LeakageTaskType;
}

function emitLeakageUxEvent(
  event: LeakageUxEventName,
  input: LeakageAnalyticsInput & {
    step?: LeakageWorkflowStep;
    dismissReason?: string;
    dismissNote?: string;
  },
): void {
  if (typeof window === "undefined") return;

  try {
    const detail: LeakageUxEventPayload = {
      event,
      workflow: "leakage",
      task_type: input.taskType,
      persona_id: input.personaId,
      session_id: getUxSessionId(),
      timestamp: new Date().toISOString(),
      ...(input.step ? { step: input.step } : {}),
      ...(input.dismissReason ? { dismiss_reason: input.dismissReason } : {}),
      ...(input.dismissNote ? { dismiss_note: input.dismissNote } : {}),
    };

    window.dispatchEvent(new CustomEvent("juli:analytics", { detail }));

    if (process.env.NODE_ENV === "development") {
      console.info(event, detail);
    }
  } catch {
    // Analytics must never break seller UX.
  }
}

/** Fail-silent analytics for leakage workflow lifecycle (issue #168, P1.7-5). */
export function trackLeakageWorkflowStarted(input: LeakageAnalyticsInput): void {
  emitLeakageUxEvent("leakage_workflow_started", input);
}

export function trackLeakageStepCompleted(
  input: LeakageAnalyticsInput & { step: LeakageWorkflowStep },
): void {
  emitLeakageUxEvent("leakage_step_completed", {
    ...input,
    step: input.step,
  });
}

export function trackLeakageWorkflowCompleted(input: LeakageAnalyticsInput): void {
  emitLeakageUxEvent("leakage_workflow_completed", input);
}

export function trackTaskDismissedWithReason(
  input: LeakageAnalyticsInput & {
    dismissReason: string;
    dismissNote?: string;
  },
): void {
  emitLeakageUxEvent("task_dismissed_with_reason", {
    ...input,
    dismissReason: input.dismissReason,
    dismissNote: input.dismissNote,
  });
}
