import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";

import type { DecisionExecutorStatus } from "./types";

export const DECISION_LIFECYCLE_SESSION_KEY = "juli_decision_lifecycle_session";

export interface DecisionLifecycleRecord {
  inputsCollected?: boolean;
  executorStatus?: DecisionExecutorStatus;
}

export interface DecisionLifecycleSession {
  version: 1;
  personaId: PersonaId;
  records: Partial<Record<ValidatedWorkflowId, DecisionLifecycleRecord>>;
}

export function createEmptyLifecycleSession(personaId: PersonaId): DecisionLifecycleSession {
  return { version: 1, personaId, records: {} };
}

export function loadDecisionLifecycleSession(personaId: PersonaId): DecisionLifecycleSession {
  if (typeof window === "undefined") {
    return createEmptyLifecycleSession(personaId);
  }

  try {
    const raw = sessionStorage.getItem(DECISION_LIFECYCLE_SESSION_KEY);
    if (!raw) {
      return createEmptyLifecycleSession(personaId);
    }

    const parsed = JSON.parse(raw) as DecisionLifecycleSession;
    if (
      parsed?.version !== 1 ||
      typeof parsed.records !== "object" ||
      parsed.personaId !== personaId
    ) {
      return createEmptyLifecycleSession(personaId);
    }

    return parsed;
  } catch {
    return createEmptyLifecycleSession(personaId);
  }
}

export function saveDecisionLifecycleSession(session: DecisionLifecycleSession): void {
  if (typeof window === "undefined") {
    return;
  }
  sessionStorage.setItem(DECISION_LIFECYCLE_SESSION_KEY, JSON.stringify(session));
}

export function clearDecisionLifecycleSession(): void {
  if (typeof window === "undefined") {
    return;
  }
  sessionStorage.removeItem(DECISION_LIFECYCLE_SESSION_KEY);
}

function updateLifecycleRecord(
  session: DecisionLifecycleSession,
  workflowId: ValidatedWorkflowId,
  patch: Partial<DecisionLifecycleRecord>,
): DecisionLifecycleSession {
  return {
    ...session,
    records: {
      ...session.records,
      [workflowId]: {
        ...session.records[workflowId],
        ...patch,
      },
    },
  };
}

export function markDecisionInputsCollected(
  session: DecisionLifecycleSession,
  workflowId: ValidatedWorkflowId,
): DecisionLifecycleSession {
  return updateLifecycleRecord(session, workflowId, { inputsCollected: true });
}

export function markDecisionExecutorExecuting(
  session: DecisionLifecycleSession,
  workflowId: ValidatedWorkflowId,
): DecisionLifecycleSession {
  return updateLifecycleRecord(session, workflowId, {
    inputsCollected: true,
    executorStatus: "executing",
  });
}

export function markDecisionExecutorCompleted(
  session: DecisionLifecycleSession,
  workflowId: ValidatedWorkflowId,
): DecisionLifecycleSession {
  return updateLifecycleRecord(session, workflowId, {
    inputsCollected: true,
    executorStatus: "completed",
  });
}
