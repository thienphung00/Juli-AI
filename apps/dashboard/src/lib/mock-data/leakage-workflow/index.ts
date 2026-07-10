import { LEAKAGE_WORKFLOW_TASKS } from "./fixtures/tasks";

export { LEAKAGE_TASK_TYPES } from "./schemas";
export type {
  LeakageActionType,
  LeakageEvidenceBundle,
  LeakageExecutionPlan,
  LeakageExecutionStep,
  LeakageMockReturn,
  LeakageRecommendedAction,
  LeakageRootCause,
  LeakageSkipReason,
  LeakageSuccessPayload,
  LeakageTaskDetail,
  LeakageTaskType,
  LeakageWorkflowStatus,
  LeakageWorkflowTask,
  OrderItem,
  ReturnTypePreview,
  RootCauseClassification,
} from "./schemas";
export { validateLeakageFixtures } from "./validate";
export type { ValidationResult } from "./validate";

export function loadLeakageFixtures() {
  return [...LEAKAGE_WORKFLOW_TASKS];
}

export function loadLeakageWorkflowTask(taskId: string) {
  return LEAKAGE_WORKFLOW_TASKS.find((task) => task.id === taskId);
}
