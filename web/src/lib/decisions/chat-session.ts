import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";

import { isValidatedWorkflowId } from "./decision";

export const DECISION_CHAT_SESSION_KEY = "juli-decision-chat-context";

export function saveActiveDecisionForChat(workflowId: ValidatedWorkflowId): void {
  if (typeof sessionStorage === "undefined") {
    return;
  }

  sessionStorage.setItem(DECISION_CHAT_SESSION_KEY, workflowId);
}

export function readActiveDecisionForChat(): ValidatedWorkflowId | null {
  if (typeof sessionStorage === "undefined") {
    return null;
  }

  const stored = sessionStorage.getItem(DECISION_CHAT_SESSION_KEY);
  if (!stored || !isValidatedWorkflowId(stored)) {
    return null;
  }

  return stored;
}

export function clearActiveDecisionForChat(): void {
  if (typeof sessionStorage === "undefined") {
    return;
  }

  sessionStorage.removeItem(DECISION_CHAT_SESSION_KEY);
}
