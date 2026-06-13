"use client";

import type { MetricDelta, ReportDomainId } from "@/lib/operations/todays-report";
import { buildDecisionsHighlightLink } from "@/lib/operations/journey-loop";
import { resolveMetricWorkflowId } from "@/lib/operations/metric-action-mapping";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

import { RealEstimatedBar } from "@/components/workflows/operations/RealEstimatedBar";

function trendColor(direction: MetricDelta["direction"]): string {
  if (direction === "up") return "var(--success)";
  if (direction === "down") return "var(--loss)";
  return "var(--brand-primary)";
}

export function ReportMetricChart({
  domainId,
  metric,
  animate,
  recommendations = [],
}: {
  domainId: ReportDomainId;
  metric: MetricDelta;
  animate: boolean;
  recommendations?: WorkflowRecommendation[];
}) {
  const workflowId = resolveMetricWorkflowId(domainId, metric.metricKey, recommendations);
  const href = workflowId ? buildDecisionsHighlightLink(workflowId) : null;
  const barColor = trendColor(metric.direction);

  return (
    <article
      className={`rounded-lg border px-3 py-3${animate ? " report-metric-chart-animate" : ""}`}
      style={{ borderColor: "var(--border)" }}
      data-testid={`report-metric-chart-${domainId}-${metric.metricKey}`}
      data-animate={animate ? "true" : "false"}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-muted text-xs font-medium uppercase tracking-wide">Reward</p>
          <h4 className="mt-0.5 text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            {metric.label}
          </h4>
          <p className="mt-1 text-base font-semibold tabular-nums">{metric.value}</p>
          {metric.deltaLabel ? (
            <span
              className="text-xs font-semibold tabular-nums"
              style={{ color: barColor }}
              data-testid="report-metric-delta"
            >
              {metric.deltaLabel}
            </span>
          ) : null}
        </div>
      </div>

      {href ? (
        <RealEstimatedBar
          realValue={metric.realValue}
          estimatedValue={metric.estimatedValue}
          scaleMax={metric.scaleMax}
          colorForValue={() => barColor}
          href={href}
          testIdPrefix={`report-metric-estimated-${domainId}-${metric.metricKey}`}
          estimatedGainLabel={metric.estimatedGainLabel}
          ariaLabel={`${metric.label}: dự kiến cải thiện nếu phê duyệt`}
        />
      ) : (
        <div
          className="mt-2 h-3 rounded-full"
          style={{ background: "color-mix(in srgb, var(--brand-primary) 14%, transparent)" }}
          data-testid={`report-metric-estimated-${domainId}-${metric.metricKey}-real-only`}
        >
          <div
            className="h-full rounded-full"
            style={{
              width: `${Math.min(100, (metric.realValue / metric.scaleMax) * 100)}%`,
              background: barColor,
            }}
          />
        </div>
      )}
    </article>
  );
}
