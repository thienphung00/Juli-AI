import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { WorkflowApprovalDisposition } from "@/lib/operations/approval-session";
import type { ImpactConfidence } from "@/lib/operations/recommendations";

export type DecisionStatus =
  | "recommended"
  | "needs_input"
  | "executing"
  | "completed";

export type DecisionExecutorStatus = "idle" | "executing" | "completed";

export interface DecisionEstimatedImpact {
  metric: string;
  value: number;
}

export interface RequiredInput {
  key: string;
  label: string;
  required: boolean;
}

export interface Decision {
  id: string;
  workflow_id: ValidatedWorkflowId;
  title: string;
  estimated_impact: DecisionEstimatedImpact;
  confidence: ImpactConfidence;
  reasoning_summary: string;
  required_inputs: RequiredInput[];
  status: DecisionStatus;
}

export interface DecisionLifecycleOptions {
  disposition?: WorkflowApprovalDisposition;
  executorStatus?: DecisionExecutorStatus;
  inputsCollected?: boolean;
  userActionRequired?: boolean;
}
