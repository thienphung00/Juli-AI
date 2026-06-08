import { LEAKAGE_TASK_TYPES, type LeakageTaskType } from "@/lib/mock-data/leakage-workflow";

export function isLeakageWorkflowTaskType(
  taskType: string,
): taskType is LeakageTaskType {
  return (LEAKAGE_TASK_TYPES as readonly string[]).includes(taskType);
}
