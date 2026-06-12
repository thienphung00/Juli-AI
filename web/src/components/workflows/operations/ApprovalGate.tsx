"use client";

import { getRequiredInputsForWorkflow } from "@/lib/decisions";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import type { WorkflowApprovalDisposition } from "@/lib/operations/approval-session";
import type { HealthCheckResults } from "@/lib/operations/health-check";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

import { ClarityCard } from "./ClarityCard";

export function ApprovalGateToolbar({
  pendingCount,
  selectedCount,
  onApproveAll,
  onApproveSelected,
  onSelectAll,
}: {
  pendingCount: number;
  selectedCount: number;
  onApproveAll: () => void;
  onApproveSelected: () => void;
  onSelectAll: () => void;
}) {
  return (
    <div
      className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
      data-testid="approval-gate-toolbar"
    >
      <div>
        <h2 className="text-base font-bold" style={{ color: "var(--foreground)" }}>
          Phê duyệt hàng loạt
        </h2>
        <p className="text-muted mt-1 text-sm">
          {pendingCount > 0
            ? `${pendingCount} đề xuất đang chờ — đọc từng thẻ trước khi phê duyệt`
            : "Tất cả đề xuất đã được xử lý trong phiên này"}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-secondary"
          data-testid="approval-select-all"
          disabled={pendingCount === 0}
          onClick={onSelectAll}
        >
          Chọn tất cả
        </button>
        <button
          type="button"
          className="btn-secondary"
          data-testid="approval-approve-selected"
          disabled={selectedCount === 0}
          onClick={onApproveSelected}
        >
          Phê duyệt đã chọn ({selectedCount})
        </button>
        <button
          type="button"
          className="btn-primary"
          data-testid="approval-approve-all"
          disabled={pendingCount === 0}
          onClick={onApproveAll}
        >
          Phê duyệt tất cả
        </button>
      </div>
    </div>
  );
}

export function OperationsRecommendationsList({
  recommendations,
  health,
  personaId,
  getDisposition,
  selectedIds,
  onToggleSelect,
  onApprove,
  onReject,
  onViewOutcome,
}: {
  recommendations: WorkflowRecommendation[];
  health: HealthCheckResults;
  personaId?: PersonaId;
  getDisposition: (workflowId: ValidatedWorkflowId) => WorkflowApprovalDisposition;
  selectedIds: Set<ValidatedWorkflowId>;
  onToggleSelect: (workflowId: ValidatedWorkflowId) => void;
  onApprove: (workflowId: ValidatedWorkflowId) => void;
  onReject: (workflowId: ValidatedWorkflowId) => void;
  onViewOutcome?: (workflowId: ValidatedWorkflowId) => void;
}) {
  if (recommendations.length === 0) {
    return (
      <p
        className="rounded-xl border px-4 py-6 text-center text-sm"
        style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
        data-testid="operations-recommendations-empty"
      >
        Không có đề xuất cho shop này.
      </p>
    );
  }

  return (
    <div className="space-y-4" data-testid="operations-recommendations-list">
      {recommendations.map((recommendation) => (
        <ClarityCard
          key={recommendation.workflow_id}
          recommendation={recommendation}
          health={health}
          personaId={personaId}
          disposition={getDisposition(recommendation.workflow_id)}
          selected={selectedIds.has(recommendation.workflow_id)}
          requiredInputs={getRequiredInputsForWorkflow(recommendation.workflow_id)}
          onToggleSelect={() => onToggleSelect(recommendation.workflow_id)}
          onApprove={() => onApprove(recommendation.workflow_id)}
          onReject={() => onReject(recommendation.workflow_id)}
          onViewOutcome={
            onViewOutcome ? () => onViewOutcome(recommendation.workflow_id) : undefined
          }
        />
      ))}
    </div>
  );
}
