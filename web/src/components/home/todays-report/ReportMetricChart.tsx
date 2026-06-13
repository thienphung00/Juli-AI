"use client";

import Link from "next/link";
import { Info } from "lucide-react";
import { useId, useState } from "react";

import { RealEstimatedBar } from "@/components/workflows/operations/RealEstimatedBar";
import { JourneyEmphasisText } from "@/components/workflows/operations/JourneyEmphasisText";
import {
  buildDecisionsHighlightLink,
  resolveJourneyLinkForMetric,
} from "@/lib/operations/journey-loop";
import { resolveMetricWorkflowId } from "@/lib/operations/metric-action-mapping";
import type { MetricDelta, ReportDomainId } from "@/lib/operations/todays-report";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

import { MetricSparkline } from "./MetricSparkline";

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
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const workflowId = resolveMetricWorkflowId(domainId, metric.metricKey, recommendations);
  const href = workflowId ? buildDecisionsHighlightLink(workflowId) : null;
  const journeyLink = resolveJourneyLinkForMetric(domainId, metric.metricKey);
  const barColor = trendColor(metric.direction);
  const hasSuggestionAccordion = Boolean(href && journeyLink?.reasonTemplate);

  function toggleExpanded() {
    setExpanded((value) => !value);
  }

  function handleToggleKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleExpanded();
    }
  }

  return (
    <article
      className={`rounded-lg border px-3 py-3${animate ? " report-metric-chart-animate" : ""}`}
      style={{ borderColor: "var(--border)" }}
      data-testid={`report-metric-chart-${domainId}-${metric.metricKey}`}
      data-animate={animate ? "true" : "false"}
    >
      {hasSuggestionAccordion ? (
        <button
          type="button"
          className="flex w-full min-h-11 items-start justify-between gap-3 rounded-md text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-offset-2"
          style={{ color: "var(--foreground)" }}
          aria-expanded={expanded}
          aria-controls={panelId}
          data-testid={`report-metric-suggestion-expand-${domainId}-${metric.metricKey}`}
          onClick={toggleExpanded}
          onKeyDown={handleToggleKeyDown}
        >
          <MetricHeader metric={metric} barColor={barColor} />
          {metric.series && metric.series.length > 1 ? (
            <MetricSparkline
              series={metric.series}
              color={barColor}
              domainId={domainId}
              metricKey={metric.metricKey}
              animate={animate}
            />
          ) : null}
        </button>
      ) : (
        <div className="flex items-start justify-between gap-3">
          <MetricHeader metric={metric} barColor={barColor} />
          {metric.series && metric.series.length > 1 ? (
            <MetricSparkline
              series={metric.series}
              color={barColor}
              domainId={domainId}
              metricKey={metric.metricKey}
              animate={animate}
            />
          ) : null}
        </div>
      )}

      {hasSuggestionAccordion && expanded ? (
        <div
          id={panelId}
          className="mt-3 space-y-2 rounded-lg border px-3 py-3"
          style={{
            borderColor: "color-mix(in srgb, var(--info) 24%, var(--border))",
            background: "color-mix(in srgb, var(--info) 6%, transparent)",
          }}
          data-testid={`report-metric-suggestion-panel-${domainId}-${metric.metricKey}`}
        >
          <div
            className="flex items-center gap-2 text-sm font-semibold"
            style={{ color: "var(--info)" }}
          >
            <Info size={16} aria-hidden="true" />
            <span>Gợi ý từ Juli</span>
          </div>
          <p className="text-sm" style={{ color: "var(--foreground)" }}>
            <JourneyEmphasisText text={journeyLink!.reasonTemplate} />
          </p>
          <Link
            href={href!}
            className="link-secondary inline-flex min-h-11 items-center text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
            style={{ color: "var(--info)" }}
            data-testid={`report-metric-cta-${domainId}-${metric.metricKey}`}
          >
            Xem quyết định liên quan →
          </Link>
        </div>
      ) : null}

      {href ? (
        <div className="mt-2">
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
        </div>
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

function MetricHeader({
  metric,
  barColor,
}: {
  metric: MetricDelta;
  barColor: string;
}) {
  return (
    <div className="min-w-0 flex-1">
      <h4 className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
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
  );
}
