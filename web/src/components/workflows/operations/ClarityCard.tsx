"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type { HealthCheckResults } from "@/lib/operations/health-check";
import { buildWorkflowReasoning } from "@/lib/operations/reasoning";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";
import { formatNumber } from "@/lib/format";

import { ReasoningPanel } from "./ReasoningPanel";

function confidenceBadgeStyle(
  confidence: WorkflowRecommendation["expected_impact"]["confidence"],
): { background: string; color: string } {
  if (confidence === "high") {
    return {
      background: "color-mix(in srgb, var(--success) 12%, transparent)",
      color: "var(--success)",
    };
  }
  if (confidence === "medium") {
    return {
      background: "color-mix(in srgb, var(--warning) 12%, transparent)",
      color: "var(--warning)",
    };
  }
  return {
    background: "color-mix(in srgb, var(--muted-foreground) 12%, transparent)",
    color: "var(--muted-foreground)",
  };
}

export function ClarityCard({
  recommendation,
  health,
}: {
  recommendation: WorkflowRecommendation;
  health: HealthCheckResults;
}) {
  const [expanded, setExpanded] = useState(false);
  const reasoning = buildWorkflowReasoning(recommendation, health);
  const { expected_impact: impact } = recommendation;

  return (
    <article
      className="card p-4"
      data-testid="clarity-card"
      data-workflow-id={recommendation.workflow_id}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-muted text-xs font-medium uppercase tracking-wide">
            Ưu tiên #{recommendation.priority}
          </p>
          <h3 className="mt-1 text-base font-semibold">{recommendation.workflow_name}</h3>
        </div>
        <span
          className="badge text-xs"
          style={confidenceBadgeStyle(impact.confidence)}
          data-testid="clarity-card-confidence"
        >
          {impact.confidence === "high"
            ? "Tin cậy cao"
            : impact.confidence === "medium"
              ? "Tin cậy TB"
              : "Tin cậy thấp"}
        </span>
      </div>

      <p className="mt-2 text-sm" data-testid="clarity-card-rationale">
        {recommendation.rationale}
      </p>

      <p className="mt-2 text-sm font-medium" data-testid="clarity-card-metric">
        {impact.metric}: {formatNumber(impact.value)}
      </p>

      <button
        type="button"
        className="btn-secondary mt-3 inline-flex w-full items-center justify-center gap-2"
        data-testid="reasoning-expand-toggle"
        aria-expanded={expanded}
        aria-controls={`reasoning-panel-${recommendation.workflow_id}`}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Thu gọn lý do" : "Xem lý do chi tiết"}
        <ChevronDown
          size={16}
          aria-hidden
          className={`transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>

      {expanded && (
        <div id={`reasoning-panel-${recommendation.workflow_id}`}>
          <ReasoningPanel reasoning={reasoning} />
        </div>
      )}
    </article>
  );
}
