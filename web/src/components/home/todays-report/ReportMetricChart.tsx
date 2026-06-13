"use client";

import Link from "next/link";

import type { MetricDelta, TrendDirection } from "@/lib/operations/todays-report";
import { buildDecisionsHighlightLink, resolveJourneyLinkForMetric } from "@/lib/operations/journey-loop";
import type { ReportDomainId } from "@/lib/operations/todays-report";

const CHART_WIDTH = 120;
const CHART_HEIGHT = 40;

function trendColor(direction: TrendDirection | undefined): string {
  if (direction === "up") return "var(--success)";
  if (direction === "down") return "var(--loss)";
  return "var(--muted-foreground)";
}

function buildSparklinePoints(series: number[]): string {
  if (series.length === 0) {
    return "";
  }

  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min || 1;

  return series
    .map((value, index) => {
      const x =
        series.length === 1 ? CHART_WIDTH / 2 : (index / (series.length - 1)) * CHART_WIDTH;
      const normalized = (value - min) / range;
      const y = CHART_HEIGHT - normalized * (CHART_HEIGHT - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");
}

export function ReportMetricChart({
  domainId,
  metric,
  animate,
}: {
  domainId: ReportDomainId;
  metric: MetricDelta;
  animate: boolean;
}) {
  const journeyLink = resolveJourneyLinkForMetric(domainId, metric.metricKey);
  const ctaHref = journeyLink ? buildDecisionsHighlightLink(journeyLink.workflowId) : null;
  const deltaColor = trendColor(metric.direction);

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
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1">
          {metric.deltaLabel ? (
            <span
              className="text-xs font-semibold tabular-nums"
              style={{ color: deltaColor }}
              data-testid="report-metric-delta"
            >
              {metric.deltaLabel}
            </span>
          ) : null}
          <svg
            width={CHART_WIDTH}
            height={CHART_HEIGHT}
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            aria-hidden="true"
            className="overflow-visible"
          >
            <polyline
              fill="none"
              stroke={deltaColor}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              points={buildSparklinePoints(metric.series)}
            />
          </svg>
        </div>
      </div>

      {ctaHref ? (
        <Link
          href={ctaHref}
          className="mt-3 inline-flex text-sm font-medium underline-offset-2 hover:underline"
          style={{ color: "var(--brand-primary)" }}
          data-testid={`report-metric-cta-${domainId}-${metric.metricKey}`}
        >
          Xem đề xuất liên quan →
        </Link>
      ) : null}
    </article>
  );
}
