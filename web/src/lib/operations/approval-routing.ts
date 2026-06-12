import { LEAKAGE_TASK_TYPES, type LeakageTaskType } from "@/lib/mock-data/leakage-workflow";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { MockTask, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";

import type { HealthCheckResults } from "./health-check";

export type WorkflowExecutionRoute = "listing" | "leakage" | "noop";

export const EXECUTABLE_WORKFLOW_IDS = [
  "npl",
  "refund_spike_detection",
] as const satisfies readonly ValidatedWorkflowId[];

export const DEFERRED_WORKFLOW_IDS = [
  "minimize_violations",
  "budget_optimization",
  "product_scaling",
  "stockout_prevention",
] as const satisfies readonly ValidatedWorkflowId[];

const REFUND_SPIKE_TASK_TYPE_PRIORITY: LeakageTaskType[] = [
  "return_spike",
  "refund_cluster",
  "buyer_cancellation_cluster",
  "return_window_policy",
];

export function getWorkflowExecutionRoute(
  workflowId: ValidatedWorkflowId,
): WorkflowExecutionRoute {
  if (workflowId === "npl") {
    return "listing";
  }
  if (workflowId === "refund_spike_detection") {
    return "leakage";
  }
  return "noop";
}

export function isExecutableWorkflow(workflowId: ValidatedWorkflowId): boolean {
  return getWorkflowExecutionRoute(workflowId) !== "noop";
}

function findLeakageTaskByType(
  persona: SellerPersona,
  taskType: LeakageTaskType,
): MockTask | undefined {
  return persona.tasks.find(
    (task) => task.workflow === "leakage" && task.type === taskType,
  );
}

/**
 * Maps refund_spike_detection to the best available P1.7 leakage task type.
 * Prefers return_spike when the health indicator reports a spike.
 */
export function resolveRefundSpikeTaskType(
  health: HealthCheckResults,
): LeakageTaskType {
  if (health.indicators.refund_spike_indicator.spike_detected) {
    return "return_spike";
  }

  return REFUND_SPIKE_TASK_TYPE_PRIORITY[0]!;
}

export function resolveTaskForWorkflow(
  workflowId: ValidatedWorkflowId,
  persona: SellerPersona,
  health: HealthCheckResults,
): MockTask | null {
  if (workflowId === "npl") {
    return persona.tasks.find((task) => task.type === "list_products") ?? null;
  }

  if (workflowId === "refund_spike_detection") {
    const preferredType = resolveRefundSpikeTaskType(health);
    const preferredTask = findLeakageTaskByType(persona, preferredType);
    if (preferredTask) {
      return preferredTask;
    }

    for (const taskType of REFUND_SPIKE_TASK_TYPE_PRIORITY) {
      const task = findLeakageTaskByType(persona, taskType);
      if (task) {
        return task;
      }
    }

    return null;
  }

  return null;
}

export function isLeakageTaskType(value: string): value is LeakageTaskType {
  return (LEAKAGE_TASK_TYPES as readonly string[]).includes(value);
}
