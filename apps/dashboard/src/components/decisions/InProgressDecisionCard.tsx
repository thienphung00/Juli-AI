"use client";

import Link from "next/link";

import { IN_PROGRESS_STATUS_LABELS, hasOutcomeTracking } from "@/lib/decisions/in-progress";
import type { Decision } from "@/lib/decisions/types";
import { formatNumber } from "@/lib/format";

export function InProgressDecisionCard({
  decision,
  onViewOutcome,
}: {
  decision: Decision;
  onViewOutcome?: () => void;
}) {
  const { workflow_id: workflowId, status } = decision;
  const statusLabel = IN_PROGRESS_STATUS_LABELS[status as Exclude<typeof status, "recommended">];

  return (
    <article
      className="card space-y-3 p-4"
      data-testid={`in-progress-decision-${workflowId}`}
      data-workflow-id={workflowId}
      data-status={status}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-base font-semibold" style={{ color: "var(--foreground)" }}>
          {decision.title}
        </h3>
        <span
          className="rounded-full px-2.5 py-0.5 text-xs font-medium"
          style={{
            background: "color-mix(in srgb, var(--primary) 12%, transparent)",
            color: "var(--primary)",
          }}
          data-testid={`in-progress-status-${status}`}
        >
          {statusLabel}
        </span>
      </div>

      <p className="text-muted text-sm">
        Tác động ước tính: +{formatNumber(decision.estimated_impact.value)}{" "}
        {decision.estimated_impact.metric}
      </p>

      {status === "needs_input" && (
        <Link
          href={`/decisions/${workflowId}?step=inputs`}
          className="btn-primary inline-flex w-full items-center justify-center focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          style={{ outlineColor: "var(--primary)" }}
          data-testid={`in-progress-resume-${workflowId}`}
        >
          Tiếp tục cung cấp thông tin
        </Link>
      )}

      {status === "executing" && (
        <p
          className="text-sm"
          style={{ color: "var(--muted-foreground)" }}
          data-testid={`in-progress-executing-copy-${workflowId}`}
        >
          Quy trình đang chạy trong phiên này — hoàn thành các bước trong cửa sổ thực thi.
        </p>
      )}

      {status === "completed" && hasOutcomeTracking(workflowId) && onViewOutcome && (
        <button
          type="button"
          className="btn-secondary w-full"
          data-testid={`in-progress-outcome-${workflowId}`}
          onClick={onViewOutcome}
        >
          Theo dõi kết quả
        </button>
      )}
    </article>
  );
}
