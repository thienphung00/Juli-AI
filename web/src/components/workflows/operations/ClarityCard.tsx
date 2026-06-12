"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type { RequiredInput } from "@/lib/decisions";
import { saveDecisionsRecommendedScroll } from "@/lib/decisions/detail-content";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { WorkflowApprovalDisposition } from "@/lib/operations/approval-session";
import type { HealthCheckResults } from "@/lib/operations/health-check";
import { trackReasoningExpansion } from "@/lib/operations/operations-analytics";
import { buildWorkflowReasoning } from "@/lib/operations/reasoning";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";
import { formatNumber } from "@/lib/format";

import { ReasoningPanel } from "./ReasoningPanel";

export function ClarityCard({
  recommendation,
  health,
  personaId,
  disposition = "pending",
  selected = false,
  requiredInputs,
  onToggleSelect,
  onApprove,
  onReject,
  onViewOutcome,
}: {
  recommendation: WorkflowRecommendation;
  health: HealthCheckResults;
  personaId?: PersonaId;
  disposition?: WorkflowApprovalDisposition;
  selected?: boolean;
  requiredInputs?: RequiredInput[];
  onToggleSelect?: () => void;
  onApprove?: () => void;
  onReject?: () => void;
  onViewOutcome?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const workflowId = recommendation.workflow_id;
  const isPending = disposition === "pending";
  const reasoning = buildWorkflowReasoning(recommendation, health);
  const { expected_impact: impact } = recommendation;

  function handleToggleExpansion() {
    setExpanded((value) => {
      const next = !value;
      if (next && personaId) {
        trackReasoningExpansion({
          workflow_id: recommendation.workflow_id,
          persona_id: personaId,
        });
      }
      return next;
    });
  }

  return (
    <article
      className="card space-y-3 p-4"
      data-testid="clarity-card"
      data-workflow-id={workflowId}
    >
      <div>
        <p className="text-muted text-xs font-medium uppercase tracking-wide">
          Ưu tiên #{recommendation.priority}
        </p>
        <h3 className="mt-1 text-base font-semibold">{recommendation.workflow_name}</h3>
      </div>

      <div>
        <p className="text-muted text-xs font-medium uppercase">Vấn đề</p>
        <p className="mt-1 text-sm" data-testid="clarity-card-rationale">
          {recommendation.rationale}
        </p>
      </div>

      <div>
        <p className="text-muted text-xs font-medium uppercase">Tác động dự kiến</p>
        <p className="mt-1 text-sm font-medium" data-testid="clarity-card-metric">
          {impact.metric}: {formatNumber(impact.value)} điểm
        </p>
      </div>

      <button
        type="button"
        className="btn-secondary inline-flex w-full items-center justify-center gap-2"
        data-testid="reasoning-expand-toggle"
        aria-expanded={expanded}
        aria-controls={`reasoning-panel-${workflowId}`}
        onClick={handleToggleExpansion}
      >
        {expanded ? "Thu gọn" : "Xem thêm"}
        <ChevronDown
          size={16}
          aria-hidden
          className={`transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>

      {expanded && (
        <div id={`reasoning-panel-${workflowId}`} className="space-y-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
          <div>
            <p className="text-muted text-xs font-medium uppercase">Vì sao quan trọng</p>
            <ReasoningPanel reasoning={reasoning} />
          </div>

          {requiredInputs && requiredInputs.length > 0 && (
            <div data-testid={`decision-required-inputs-${workflowId}`}>
              <p className="text-sm font-medium" style={{ color: "var(--foreground)" }}>
                Thông tin cần có
              </p>
              <ul className="text-muted mt-1 list-inside list-disc text-sm">
                {requiredInputs.map((input) => (
                  <li key={input.key}>
                    {input.label}
                    {!input.required ? " (tùy chọn)" : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <Link
            href={`/decisions/${workflowId}`}
            className="link-secondary inline-block"
            data-testid={`decision-review-${workflowId}`}
            onClick={saveDecisionsRecommendedScroll}
          >
            Chi tiết đầy đủ →
          </Link>
        </div>
      )}

      {disposition === "approved" && (
        <div className="space-y-2 border-t pt-3" style={{ borderColor: "var(--border)" }}>
          <p
            className="text-sm font-medium"
            style={{ color: "var(--success)" }}
            data-testid={`approval-status-approved-${workflowId}`}
          >
            Đã phê duyệt
          </p>
          {onViewOutcome && (
            <button
              type="button"
              className="btn-secondary w-full"
              data-testid={`outcome-view-${workflowId}`}
              onClick={onViewOutcome}
            >
              Báo cáo tuần
            </button>
          )}
        </div>
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

      {isPending && onApprove && onReject && (
        <div className="space-y-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
          {onToggleSelect && (
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
        </div>
      )}
    </article>
  );
}
