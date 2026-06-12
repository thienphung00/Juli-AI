import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { TaskDismissReason } from "@/lib/task-executor/dismiss-reasons";

export type WorkflowApprovalDisposition = "pending" | "approved" | "rejected";

export interface WorkflowApprovalRecord {
  disposition: WorkflowApprovalDisposition;
  updatedAt: string;
  dismissReason?: TaskDismissReason;
  dismissNote?: string;
}

export interface OperationsApprovalSession {
  version: 1;
  personaId: PersonaId;
  records: Partial<Record<ValidatedWorkflowId, WorkflowApprovalRecord>>;
}

export const OPERATIONS_APPROVAL_SESSION_KEY = "juli_operations_approval_session";

export function createEmptyApprovalSession(
  personaId: PersonaId,
): OperationsApprovalSession {
  return { version: 1, personaId, records: {} };
}

export function loadOperationsApprovalSession(
  personaId: PersonaId,
): OperationsApprovalSession {
  if (typeof window === "undefined") {
    return createEmptyApprovalSession(personaId);
  }

  try {
    const raw = sessionStorage.getItem(OPERATIONS_APPROVAL_SESSION_KEY);
    if (!raw) {
      return createEmptyApprovalSession(personaId);
    }

    const parsed = JSON.parse(raw) as OperationsApprovalSession;
    if (
      parsed?.version !== 1 ||
      typeof parsed.records !== "object" ||
      parsed.personaId !== personaId
    ) {
      return createEmptyApprovalSession(personaId);
    }

    return parsed;
  } catch {
    return createEmptyApprovalSession(personaId);
  }
}

export function saveOperationsApprovalSession(
  session: OperationsApprovalSession,
): void {
  if (typeof window === "undefined") {
    return;
  }
  sessionStorage.setItem(OPERATIONS_APPROVAL_SESSION_KEY, JSON.stringify(session));
}

export function clearOperationsApprovalSession(): void {
  if (typeof window === "undefined") {
    return;
  }
  sessionStorage.removeItem(OPERATIONS_APPROVAL_SESSION_KEY);
}

export function getWorkflowDisposition(
  session: OperationsApprovalSession,
  workflowId: ValidatedWorkflowId,
): WorkflowApprovalDisposition {
  return session.records[workflowId]?.disposition ?? "pending";
}

export function setWorkflowDisposition(
  session: OperationsApprovalSession,
  workflowId: ValidatedWorkflowId,
  disposition: Exclude<WorkflowApprovalDisposition, "pending">,
  options?: { dismissReason?: TaskDismissReason; dismissNote?: string },
): OperationsApprovalSession {
  return {
    ...session,
    records: {
      ...session.records,
      [workflowId]: {
        disposition,
        updatedAt: new Date().toISOString(),
        ...(options?.dismissReason ? { dismissReason: options.dismissReason } : {}),
        ...(options?.dismissNote ? { dismissNote: options.dismissNote } : {}),
      },
    },
  };
}
