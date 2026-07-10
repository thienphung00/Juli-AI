import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import {
  getWorkflowDisposition,
  type OperationsApprovalSession,
} from "@/lib/operations/approval-session";
import {
  getWorkflowExecutionRoute,
  resolveTaskForWorkflow,
} from "@/lib/operations/approval-routing";
import type { HealthCheckResults } from "@/lib/operations/health-check";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";
import type { TaskExecutorSession } from "@/lib/task-executor/types";

import { applyDecisionLifecycle, sortDecisionsByImpact, toDecision } from "./decision";
import type { DecisionLifecycleSession } from "./lifecycle-store";
import type { Decision, DecisionExecutorStatus, DecisionStatus } from "./types";

export const IN_PROGRESS_STATUS_LABELS: Record<
  Exclude<DecisionStatus, "recommended">,
  string
> = {
  needs_input: "Cần thông tin",
  executing: "Đang thực hiện",
  completed: "Hoàn tất",
};

export interface InProgressDecisionContext {
  approvalSession: OperationsApprovalSession;
  lifecycleSession: DecisionLifecycleSession;
  executorSession: TaskExecutorSession;
  persona: SellerPersona;
  health: HealthCheckResults;
}

export function filterApprovedRecommendations(
  recommendations: WorkflowRecommendation[],
  approvalSession: OperationsApprovalSession,
): WorkflowRecommendation[] {
  return recommendations.filter(
    (item) => getWorkflowDisposition(approvalSession, item.workflow_id) === "approved",
  );
}

export function resolveWorkflowExecutorStatus(
  workflowId: ValidatedWorkflowId,
  context: Pick<
    InProgressDecisionContext,
    "lifecycleSession" | "executorSession" | "persona" | "health"
  >,
): DecisionExecutorStatus | undefined {
  const lifecycleRecord = context.lifecycleSession.records[workflowId];

  if (lifecycleRecord?.executorStatus === "completed") {
    return "completed";
  }

  if (lifecycleRecord?.executorStatus === "executing") {
    return "executing";
  }

  const task = resolveTaskForWorkflow(workflowId, context.persona, context.health);
  if (task && context.executorSession.records[task.id]?.disposition === "approved") {
    return "executing";
  }

  return lifecycleRecord?.executorStatus;
}

export function toInProgressDecision(
  recommendation: WorkflowRecommendation,
  context: InProgressDecisionContext,
): Decision {
  const lifecycleRecord = context.lifecycleSession.records[recommendation.workflow_id];
  const executorStatus = resolveWorkflowExecutorStatus(recommendation.workflow_id, context);

  return applyDecisionLifecycle(toDecision(recommendation), {
    disposition: "approved",
    userActionRequired: recommendation.user_action_required,
    inputsCollected: lifecycleRecord?.inputsCollected ?? executorStatus !== undefined,
    executorStatus,
  });
}

export function buildInProgressDecisions(
  recommendations: WorkflowRecommendation[],
  context: InProgressDecisionContext,
): Decision[] {
  const approved = filterApprovedRecommendations(recommendations, context.approvalSession);
  const decisions = approved.map((item) => toInProgressDecision(item, context));
  return sortDecisionsByImpact(decisions);
}

export function hasOutcomeTracking(workflowId: ValidatedWorkflowId): boolean {
  return getWorkflowExecutionRoute(workflowId) !== "noop";
}
