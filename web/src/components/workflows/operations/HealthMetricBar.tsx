"use client";

import { formatNumber } from "@/lib/format";
import { formatHealthScoreGainLabel } from "@/lib/operations/estimated-gain-label";
import {
  AHR_SCALE_MAX,
  AHR_METRIC,
  SPS_METRIC,
  SPS_SCALE_MAX,
  SPS_THRESHOLD_TICKS,
  formatSpsThresholdLabel,
  healthRampColor,
} from "@/lib/metrics/shop-health-metrics";
import { buildDecisionsHighlightLink } from "@/lib/operations/journey-loop";
import {
  resolveAhrWorkflowId,
  resolveSpsWorkflowId,
} from "@/lib/operations/metric-action-mapping";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

import { RealEstimatedBar } from "./RealEstimatedBar";

function spsUnlockLabel(current: number, estimated: number): string | undefined {
  if (current < 4.5 && estimated >= 4.5) {
    return "Star Shop";
  }
  if (current < 3.5 && estimated >= 3.5) {
    return "Mega-campaign";
  }
  return undefined;
}

export function HealthMetricBar({
  label,
  description,
  current,
  estimated,
  scaleMax,
  testId,
  metricKind,
  recommendations,
}: {
  label: string;
  description: string;
  current: number;
  estimated: number;
  scaleMax: number;
  testId: string;
  metricKind: "sps" | "ahr";
  recommendations: WorkflowRecommendation[];
}) {
  const workflowId =
    metricKind === "sps" ? resolveSpsWorkflowId(recommendations) : resolveAhrWorkflowId(recommendations);
  const href = buildDecisionsHighlightLink(workflowId) ?? "/decisions";
  const unlock =
    metricKind === "sps" ? spsUnlockLabel(current, estimated) : undefined;
  const gainTooltip = formatHealthScoreGainLabel(
    current,
    estimated,
    label,
    unlock,
  );

  return (
    <div data-testid={testId}>
      <div className="flex items-end justify-between gap-2">
        <div>
          <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            {label}
          </p>
          <p className="text-muted mt-0.5 text-xs">{description}</p>
        </div>
        <p
          className="text-right text-sm font-bold tabular-nums"
          style={{ color: "var(--brand-primary)" }}
        >
          {formatNumber(current)}
          <span className="text-muted font-medium"> → {formatNumber(estimated)}</span>
        </p>
      </div>

      <RealEstimatedBar
        realValue={current}
        estimatedValue={estimated}
        scaleMax={scaleMax}
        colorForValue={(value) => healthRampColor(value, scaleMax)}
        href={href}
        testIdPrefix={testId}
        estimatedGainLabel={gainTooltip}
        ariaLabel={`${label}: ${formatNumber(current)} dự kiến ${formatNumber(estimated)}`}
        thresholdTicks={metricKind === "sps" ? SPS_THRESHOLD_TICKS : []}
      />

      {metricKind === "sps" ? (
        <div
          className="text-muted mt-1 flex flex-wrap gap-2 text-xs"
          aria-hidden="true"
        >
          {SPS_THRESHOLD_TICKS.map((tick) => (
            <span key={tick}>
              {formatNumber(tick)} — {formatSpsThresholdLabel(tick)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function deriveShopHealthEstimates(
  spsCurrent: number,
  ahrCurrent: number,
  recommendations: WorkflowRecommendation[],
): { spsEstimated: number; ahrEstimated: number } {
  const spsRec = recommendations.find(
    (item) => item.workflow_id === resolveSpsWorkflowId(recommendations),
  );
  const ahrRec = recommendations.find(
    (item) => item.workflow_id === resolveAhrWorkflowId(recommendations),
  );

  const spsDelta =
    spsRec?.expected_impact.metric === "SPS" ? spsRec.expected_impact.value : 0.4;
  const ahrDelta =
    ahrRec?.expected_impact.metric === "AHR" ? ahrRec.expected_impact.value : 6;

  return {
    spsEstimated: Math.min(SPS_SCALE_MAX, Math.round((spsCurrent + spsDelta) * 10) / 10),
    ahrEstimated: Math.min(AHR_SCALE_MAX, Math.round(ahrCurrent + ahrDelta)),
  };
}
