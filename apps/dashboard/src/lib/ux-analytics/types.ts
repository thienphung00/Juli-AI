import type { PersonaId, WorkflowId } from "@/lib/mock-data/seller-personas/schemas";

export type TaskUxEventName =
  | "task_clicked"
  | "task_approved"
  | "task_dismissed";

export interface TaskUxEventPayload {
  event: TaskUxEventName;
  workflow: WorkflowId;
  task_type: string;
  persona_id: PersonaId;
  session_id: string;
  timestamp: string;
  dismiss_reason?: string;
  dismiss_note?: string;
}
