export const DECISION_DETAIL_STEPS = [
  "why",
  "analytics",
  "inputs",
  "preview",
  "approve",
] as const;

export type DecisionDetailStep = (typeof DECISION_DETAIL_STEPS)[number];

export const DECISION_DETAIL_STEP_LABELS: Record<DecisionDetailStep, string> = {
  why: "Tại sao",
  analytics: "Phân tích",
  inputs: "Thông tin của bạn",
  preview: "Xem trước",
  approve: "Phê duyệt",
};

export function getStepIndex(step: DecisionDetailStep): number {
  return DECISION_DETAIL_STEPS.indexOf(step);
}

export function isFirstStep(step: DecisionDetailStep): boolean {
  return getStepIndex(step) === 0;
}

export function isLastStep(step: DecisionDetailStep): boolean {
  return getStepIndex(step) === DECISION_DETAIL_STEPS.length - 1;
}

export function getNextStep(step: DecisionDetailStep): DecisionDetailStep | null {
  const index = getStepIndex(step);
  if (index < 0 || index >= DECISION_DETAIL_STEPS.length - 1) {
    return null;
  }
  return DECISION_DETAIL_STEPS[index + 1]!;
}

export function getPreviousStep(step: DecisionDetailStep): DecisionDetailStep | null {
  const index = getStepIndex(step);
  if (index <= 0) {
    return null;
  }
  return DECISION_DETAIL_STEPS[index - 1]!;
}
