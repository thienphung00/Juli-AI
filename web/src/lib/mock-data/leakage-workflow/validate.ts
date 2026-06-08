import { collectForbiddenPiiKeys, isMaskedBuyerId } from "@/lib/mock-data/seller-personas/pii";
import { LEAKAGE_WORKFLOW_TASKS } from "./fixtures/tasks";
import type { LeakageWorkflowTask } from "./schemas";
import { LEAKAGE_TASK_TYPES } from "./schemas";

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function validateLeakageTask(task: LeakageWorkflowTask, errors: string[], index: number): void {
  const prefix = `tasks[${index}]`;

  if (!isNonEmptyString(task.id)) errors.push(`${prefix}.id is required`);
  if (task.workflow !== "leakage") errors.push(`${prefix}.workflow must be "leakage"`);
  if (!LEAKAGE_TASK_TYPES.includes(task.type)) {
    errors.push(`${prefix}.type must be a valid leakage task type`);
  }
  if (!["high", "medium", "low", "info"].includes(task.severity)) {
    errors.push(`${prefix}.severity is invalid`);
  }
  if (!isNonEmptyString(task.title)) errors.push(`${prefix}.title is required`);
  if (!isNonEmptyString(task.body)) errors.push(`${prefix}.body is required`);
  if (!isNonEmptyString(task.cta_label)) errors.push(`${prefix}.cta_label is required`);
  if (task.estimated_impact_vnd !== null && !isFiniteNumber(task.estimated_impact_vnd)) {
    errors.push(`${prefix}.estimated_impact_vnd must be null or a number`);
  }
  if (!Array.isArray(task.evidence_refs)) {
    errors.push(`${prefix}.evidence_refs must be an array`);
  }
  if (!["mock", "rules", "ollama"].includes(task.copy_source)) {
    errors.push(`${prefix}.copy_source is invalid`);
  }
  if (!isNonEmptyString(task.detail?.summary_vi)) {
    errors.push(`${prefix}.detail.summary_vi is required`);
  }
  if (!task.root_cause || !isNonEmptyString(task.root_cause.summary_vi)) {
    errors.push(`${prefix}.root_cause.summary_vi is required`);
  }
  if (
    !isFiniteNumber(task.root_cause.confidence) ||
    task.root_cause.confidence < 0 ||
    task.root_cause.confidence > 1
  ) {
    errors.push(`${prefix}.root_cause.confidence must be between 0 and 1`);
  }
  if (!task.recommended_action || !isNonEmptyString(task.recommended_action.summary_vi)) {
    errors.push(`${prefix}.recommended_action.summary_vi is required`);
  }
  if (!Array.isArray(task.execution_plan?.steps) || task.execution_plan.steps.length === 0) {
    errors.push(`${prefix}.execution_plan.steps must be a non-empty array`);
  }
  if (!task.success || !isNonEmptyString(task.success.headline_vi)) {
    errors.push(`${prefix}.success.headline_vi is required`);
  }
  if (!Array.isArray(task.success?.metrics_vi) || task.success.metrics_vi.length === 0) {
    errors.push(`${prefix}.success.metrics_vi must be a non-empty array`);
  }

  for (const [orderIndex, order] of task.evidence_bundle.orders.entries()) {
    if (!isMaskedBuyerId(order.buyer_id)) {
      errors.push(`${prefix}.evidence_bundle.orders[${orderIndex}].buyer_id must be masked`);
    }
  }
  for (const [returnIndex, ret] of task.evidence_bundle.returns.entries()) {
    if (!isMaskedBuyerId(ret.buyer_id)) {
      errors.push(`${prefix}.evidence_bundle.returns[${returnIndex}].buyer_id must be masked`);
    }
  }
}

export function validateLeakageFixtures(): ValidationResult {
  const errors: string[] = [];

  if (LEAKAGE_WORKFLOW_TASKS.length !== LEAKAGE_TASK_TYPES.length) {
    errors.push(
      `expected ${LEAKAGE_TASK_TYPES.length} tasks, got ${LEAKAGE_WORKFLOW_TASKS.length}`,
    );
  }

  const types = new Set(LEAKAGE_WORKFLOW_TASKS.map((task) => task.type));
  for (const expectedType of LEAKAGE_TASK_TYPES) {
    if (!types.has(expectedType)) {
      errors.push(`missing task type: ${expectedType}`);
    }
  }

  LEAKAGE_WORKFLOW_TASKS.forEach((task, index) => validateLeakageTask(task, errors, index));

  const piiViolations = collectForbiddenPiiKeys(LEAKAGE_WORKFLOW_TASKS);
  piiViolations.forEach((path) => errors.push(`forbidden PII key at ${path}`));

  return { valid: errors.length === 0, errors };
}
