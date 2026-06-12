import {
  VALIDATED_WORKFLOW_IDS,
  type ValidatedWorkflowId,
} from "@/lib/mock-data/operations/schemas";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

import { getRequiredInputsForWorkflow } from "./required-inputs";
import type {
  Decision,
  DecisionLifecycleOptions,
  DecisionStatus,
} from "./types";

export class InvalidWorkflowIdError extends Error {
  constructor(workflowId: string) {
    super(`Unknown workflow_id: ${workflowId}`);
    this.name = "InvalidWorkflowIdError";
  }
}

export function isValidatedWorkflowId(value: string): value is ValidatedWorkflowId {
  return (VALIDATED_WORKFLOW_IDS as readonly string[]).includes(value);
}

export function toDecision(recommendation: WorkflowRecommendation): Decision {
  if (!isValidatedWorkflowId(recommendation.workflow_id)) {
    throw new InvalidWorkflowIdError(recommendation.workflow_id);
  }

  return {
    id: recommendation.workflow_id,
    workflow_id: recommendation.workflow_id,
    title: recommendation.workflow_name,
    estimated_impact: {
      metric: recommendation.expected_impact.metric,
      value: recommendation.expected_impact.value,
    },
    confidence: recommendation.expected_impact.confidence,
    reasoning_summary: recommendation.rationale,
    required_inputs: getRequiredInputsForWorkflow(recommendation.workflow_id),
    status: "recommended",
  };
}

export function toDecisionsFromRecommendations(
  recommendations: WorkflowRecommendation[],
): Decision[] {
  return recommendations
    .filter((item) => isValidatedWorkflowId(item.workflow_id))
    .map((item) => toDecision(item));
}

export function sortDecisionsByImpact(decisions: Decision[]): Decision[] {
  return [...decisions].sort((left, right) => {
    const impactDelta = right.estimated_impact.value - left.estimated_impact.value;
    if (impactDelta !== 0) {
      return impactDelta;
    }

    return left.id.localeCompare(right.id);
  });
}

export function takeTopDecisions(decisions: Decision[], count: number): Decision[] {
  if (count <= 0) {
    return [];
  }

  return sortDecisionsByImpact(decisions).slice(0, count);
}

export function resolveDecisionStatus(
  options: DecisionLifecycleOptions,
): DecisionStatus {
  const disposition = options.disposition ?? "pending";

  if (disposition !== "approved") {
    return "recommended";
  }

  if (options.executorStatus === "completed") {
    return "completed";
  }

  if (options.executorStatus === "executing") {
    return "executing";
  }

  if (options.userActionRequired && !options.inputsCollected) {
    return "needs_input";
  }

  return "executing";
}

export function applyDecisionLifecycle(
  decision: Decision,
  options: DecisionLifecycleOptions,
): Decision {
  return {
    ...decision,
    status: resolveDecisionStatus(options),
  };
}
