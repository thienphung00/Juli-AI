"use client";

import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
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
          Cổng phê duyệt
        </h2>
        <p className="text-muted mt-1 text-sm">
          {pendingCount > 0
            ? `${pendingCount} gợi ý đang chờ quyết định`
            : "Tất cả gợi ý đã được xử lý trong phiên này"}
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

export function ApprovalClarityCard({
  recommendation,
  health,
  disposition,
  selected,
  onToggleSelect,
  onApprove,
  onReject,
}: {
  recommendation: WorkflowRecommendation;
  health: HealthCheckResults;
  disposition: WorkflowApprovalDisposition;
  selected: boolean;
  onToggleSelect: () => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const workflowId = recommendation.workflow_id;
  const isPending = disposition === "pending";

  return (
    <div className="space-y-3" data-testid="approval-clarity-card" data-workflow-id={workflowId}>
      {isPending && (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelect}
            data-testid={`approval-select-${workflowId}`}
          />
          <span>Chọn để phê duyệt hàng loạt</span>
        </label>
      )}

      <ClarityCard recommendation={recommendation} health={health} />

      {disposition === "approved" && (
        <p
          className="text-sm font-medium"
          style={{ color: "var(--success)" }}
          data-testid={`approval-status-approved-${workflowId}`}
        >
          Đã phê duyệt
        </p>
      )}

      {disposition === "rejected" && (
        <p
          className="text-sm font-medium"
          style={{ color: "var(--muted-foreground)" }}
          data-testid={`approval-status-rejected-${workflowId}`}
        >
          Đã từ chối
        </p>
      )}

      {isPending && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary flex-1"
            data-testid={`approval-approve-${workflowId}`}
            onClick={onApprove}
          >
            Phê duyệt
          </button>
          <button
            type="button"
            className="btn-secondary flex-1"
            data-testid={`approval-reject-${workflowId}`}
            onClick={onReject}
          >
            Từ chối
          </button>
        </div>
      )}
    </div>
  );
}

export function OperationsRecommendationsList({
  recommendations,
  health,
  getDisposition,
  selectedIds,
  onToggleSelect,
  onApprove,
  onReject,
}: {
  recommendations: WorkflowRecommendation[];
  health: HealthCheckResults;
  getDisposition: (workflowId: ValidatedWorkflowId) => WorkflowApprovalDisposition;
  selectedIds: Set<ValidatedWorkflowId>;
  onToggleSelect: (workflowId: ValidatedWorkflowId) => void;
  onApprove: (workflowId: ValidatedWorkflowId) => void;
  onReject: (workflowId: ValidatedWorkflowId) => void;
}) {
  if (recommendations.length === 0) {
    return (
      <p
        className="rounded-xl border px-4 py-6 text-center text-sm"
        style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
        data-testid="operations-recommendations-empty"
      >
        Không có gợi ý quy trình cho shop này.
      </p>
    );
  }

  return (
    <div className="space-y-4" data-testid="operations-recommendations-list">
      {recommendations.map((recommendation) => (
        <ApprovalClarityCard
          key={recommendation.workflow_id}
          recommendation={recommendation}
          health={health}
          disposition={getDisposition(recommendation.workflow_id)}
          selected={selectedIds.has(recommendation.workflow_id)}
          onToggleSelect={() => onToggleSelect(recommendation.workflow_id)}
          onApprove={() => onApprove(recommendation.workflow_id)}
          onReject={() => onReject(recommendation.workflow_id)}
        />
      ))}
    </div>
  );
}
