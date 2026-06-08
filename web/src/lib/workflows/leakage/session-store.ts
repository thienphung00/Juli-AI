import { LEAKAGE_WORKFLOW_SESSION_PREFIX } from "./constants";
import type { LeakageWorkflowSessionState } from "./state-machine";

export interface LeakageWorkflowSession {
  version: 1;
  taskId: string;
  state: LeakageWorkflowSessionState;
}

export function leakageWorkflowStorageKey(taskId: string): string {
  return `${LEAKAGE_WORKFLOW_SESSION_PREFIX}${taskId}`;
}

export function loadLeakageWorkflowSession(
  taskId: string,
): LeakageWorkflowSession | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = sessionStorage.getItem(leakageWorkflowStorageKey(taskId));
    if (!raw) return null;

    const parsed = JSON.parse(raw) as LeakageWorkflowSession;
    if (
      parsed?.version !== 1 ||
      parsed.taskId !== taskId ||
      !parsed.state ||
      typeof parsed.state.step !== "string" ||
      typeof parsed.state.workflowStatus !== "string"
    ) {
      return null;
    }

    return parsed;
  } catch {
    return null;
  }
}

export function saveLeakageWorkflowSession(session: LeakageWorkflowSession): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(
    leakageWorkflowStorageKey(session.taskId),
    JSON.stringify(session),
  );
}

export function clearLeakageWorkflowSession(taskId: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(leakageWorkflowStorageKey(taskId));
}
