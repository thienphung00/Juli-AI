"use client";

import type { Decision } from "@/lib/decisions";
import { formatNumber } from "@/lib/format";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";

const LOSS_PREVENTION_WORKFLOW_IDS = new Set<ValidatedWorkflowId>([
  "refund_spike_detection",
  "stockout_prevention",
  "minimize_violations",
]);

function impactValueLabel(workflowId: ValidatedWorkflowId): string {
  return LOSS_PREVENTION_WORKFLOW_IDS.has(workflowId)
    ? "Ngăn rò rỉ dự kiến"
    : "Tăng doanh thu dự kiến";
}

export function DecisionPreviewCard({ decision }: { decision: Decision }) {
  const { estimated_impact: impact } = decision;

  return (
    <article
      className="card p-4"
      data-testid="decision-preview-card"
      data-workflow-id={decision.workflow_id}
    >
      <h3 className="text-base font-semibold" data-testid="decision-preview-title">
        {decision.title}
      </h3>

      <p className="text-muted mt-1 text-sm" data-testid="decision-preview-impact-metric">
        {impact.metric}: {formatNumber(impact.value)}
      </p>

      <p className="mt-2 text-sm font-medium" data-testid="decision-preview-impact-value">
        {impactValueLabel(decision.workflow_id)}: {formatNumber(impact.value)}
      </p>
    </article>
  );
}
