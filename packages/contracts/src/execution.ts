export type ExecutionTimelineStepStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed";

export type ExecutionLifecycleStatus =
  | "needs_input"
  | "executing"
  | "completed";

export type ExecutionTimelineStepKind = "action" | "wait" | "outcome";

export interface ExecutionTimelineStep {
  id: string;
  stepNumber: number;
  kind: ExecutionTimelineStepKind;
  title: string;
  description: string;
  status: ExecutionTimelineStepStatus;
  recoveryText?: string;
  errorText?: string;
}

export interface ExecutionRecord {
  executionId: string;
  workflowKey: string;
  toolName: string;
  lifecycleStatus: ExecutionLifecycleStatus;
  startedAt: string;
  updatedAt: string;
  timeline: ExecutionTimelineStep[];
  approvedInputs: Record<string, string>;
}

export function deriveLifecycleFromTimeline(
  timeline: ExecutionTimelineStep[],
): ExecutionLifecycleStatus {
  const terminalOutcome = timeline
    .filter((step) => step.kind === "outcome")
    .reduce<ExecutionTimelineStep | undefined>(
      (latest, step) =>
        latest === undefined || step.stepNumber > latest.stepNumber
          ? step
          : latest,
      undefined,
    );

  if (terminalOutcome?.status === "succeeded") {
    return "completed";
  }

  const eligibilityOutcome = timeline.find(
    (step) => step.id === "eligibility-outcome" && step.status === "failed",
  );
  if (eligibilityOutcome) {
    return "needs_input";
  }

  const needsInputStep = timeline.find(
    (step) =>
      step.kind === "outcome" &&
      step.status === "running" &&
      step.recoveryText !== undefined,
  );
  if (needsInputStep) {
    return "needs_input";
  }

  const activeStep = timeline.find(
    (step) => step.status === "running" || step.status === "failed",
  );

  if (activeStep?.status === "failed") {
    return "needs_input";
  }

  return "executing";
}
