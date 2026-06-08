import type { LeakageWorkflowStatus } from "@/lib/mock-data/leakage-workflow/schemas";

export type LeakageWorkflowStep =
  | "detail"
  | "evidence"
  | "root_cause"
  | "recommended_action"
  | "execution"
  | "success";

export const LEAKAGE_WORKFLOW_STEPS: LeakageWorkflowStep[] = [
  "detail",
  "evidence",
  "root_cause",
  "recommended_action",
  "execution",
  "success",
];

export interface LeakageWorkflowSessionState {
  taskId: string;
  step: LeakageWorkflowStep;
  workflowStatus: LeakageWorkflowStatus;
  evidenceReviewed: boolean;
  piiGuardPassed: boolean;
}

const STATUS_BY_STEP: Record<LeakageWorkflowStep, LeakageWorkflowStatus> = {
  detail: "new",
  evidence: "in_review",
  root_cause: "evidence_reviewed",
  recommended_action: "ready_to_execute",
  execution: "executing",
  success: "completed",
};

export function workflowStatusForStep(
  step: LeakageWorkflowStep,
): LeakageWorkflowStatus {
  return STATUS_BY_STEP[step];
}

export function createInitialLeakageWorkflowState(
  taskId: string,
  piiGuardPassed: boolean,
): LeakageWorkflowSessionState {
  return {
    taskId,
    step: "detail",
    workflowStatus: "new",
    evidenceReviewed: false,
    piiGuardPassed,
  };
}

export function markEvidenceReviewed(
  state: LeakageWorkflowSessionState,
): LeakageWorkflowSessionState {
  return { ...state, evidenceReviewed: true };
}

export function canAdvanceLeakage(state: LeakageWorkflowSessionState): boolean {
  switch (state.step) {
    case "detail":
      return true;
    case "evidence":
      return state.evidenceReviewed && state.piiGuardPassed;
    case "root_cause":
    case "recommended_action":
    case "execution":
      return true;
    case "success":
      return false;
    default:
      return false;
  }
}

export function advanceLeakageStep(
  state: LeakageWorkflowSessionState,
): LeakageWorkflowSessionState {
  if (!canAdvanceLeakage(state)) return state;

  const index = LEAKAGE_WORKFLOW_STEPS.indexOf(state.step);
  if (index < 0 || index >= LEAKAGE_WORKFLOW_STEPS.length - 1) return state;

  const nextStep = LEAKAGE_WORKFLOW_STEPS[index + 1]!;
  return {
    ...state,
    step: nextStep,
    workflowStatus: workflowStatusForStep(nextStep),
  };
}

export function canGoBackLeakage(state: LeakageWorkflowSessionState): boolean {
  return LEAKAGE_WORKFLOW_STEPS.indexOf(state.step) > 0;
}

export function goBackLeakageStep(
  state: LeakageWorkflowSessionState,
): LeakageWorkflowSessionState {
  if (!canGoBackLeakage(state)) return state;

  const index = LEAKAGE_WORKFLOW_STEPS.indexOf(state.step);
  const previousStep = LEAKAGE_WORKFLOW_STEPS[index - 1]!;
  return {
    ...state,
    step: previousStep,
    workflowStatus: workflowStatusForStep(previousStep),
  };
}

export function skipLeakageWorkflow(
  state: LeakageWorkflowSessionState,
): LeakageWorkflowSessionState {
  return { ...state, workflowStatus: "skipped" };
}
