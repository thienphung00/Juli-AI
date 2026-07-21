"use client";

import type { ChartTrend } from "@juli/ui";
import {
  MetricSparkline,
  ProgressBar,
  TrendAreaChart,
  TrendLineChart,
} from "@juli/ui";

import type { ChartKind } from "../lib/analytics/main-kpis";
import type { KpiSnapshot } from "../lib/analytics/mock-data";

interface AnalyticsHeroChartProps {
  chartKind: ChartKind;
  label: string;
  snapshot: KpiSnapshot;
  comparePreviousPeriod: boolean;
}

export function AnalyticsHeroChart({
  chartKind,
  label,
  snapshot,
  comparePreviousPeriod,
}: AnalyticsHeroChartProps) {
  const previousData = comparePreviousPeriod
    ? snapshot.previousTimeSeries
    : undefined;

  if (chartKind === "gauge" && snapshot.gaugeValue !== undefined) {
    return (
      <figure className="analytics-hero-chart analytics-hero-chart--gauge">
        <p className="juli-sr-only">
          {label} — {snapshot.formattedValue} — {snapshot.delta}
        </p>
        <ProgressBar label={label} value={snapshot.gaugeValue} />
        <p aria-hidden="true" className="analytics-hero-chart__gauge-value">
          {snapshot.formattedValue}
        </p>
      </figure>
    );
  }

  if (chartKind === "forecast-line") {
    const overlayData = comparePreviousPeriod
      ? previousData
      : snapshot.forecastSeries;

    return (
      <TrendLineChart
        currentData={snapshot.timeSeries}
        delta={snapshot.delta}
        label={label}
        previousData={overlayData}
        trend={snapshot.trend}
        value={snapshot.formattedValue}
        width={320}
      />
    );
  }

  if (chartKind === "trend-line") {
    return (
      <TrendAreaChart
        data={snapshot.timeSeries}
        delta={snapshot.delta}
        label={label}
        trend={snapshot.trend as ChartTrend}
        value={snapshot.formattedValue}
        width={320}
      />
    );
  }

  return null;
}

interface AnalyticsPreviewChartProps {
  label: string;
  sparkline: readonly number[];
  trend: ChartTrend;
  value: string;
  delta: string;
}

export function AnalyticsPreviewChart({
  label,
  sparkline,
  trend,
  value,
  delta,
}: AnalyticsPreviewChartProps) {
  return (
    <div aria-hidden="true" className="analytics-kpi-card__preview">
      <MetricSparkline
        data={sparkline}
        delta={delta}
        height={32}
        label={label}
        trend={trend}
        value={value}
        width={96}
      />
    </div>
  );
}

export function AnalyticsUnavailableChartPattern() {
  return (
    <div
      aria-hidden="true"
      className="analytics-unavailable-chart"
      data-testid="analytics-unavailable-chart"
    >
      <svg focusable="false" viewBox="0 0 120 40">
        <line
          stroke="var(--juli-border)"
          strokeDasharray="4 4"
          x1="0"
          x2="120"
          y1="20"
          y2="20"
        />
        <line
          stroke="var(--juli-border)"
          strokeDasharray="2 6"
          x1="0"
          x2="120"
          y1="8"
          y2="8"
        />
        <line
          stroke="var(--juli-border)"
          strokeDasharray="2 6"
          x1="0"
          x2="120"
          y1="32"
          y2="32"
        />
      </svg>
    </div>
  );
}
