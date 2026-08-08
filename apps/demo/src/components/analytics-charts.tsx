"use client";

import type { ChartTrend } from "@juli/ui";
import {
  MetricSparkline,
  ProgressBar,
  TrendAreaChart,
  TrendLineChart,
} from "@juli/ui";

import type {
  ChartKind,
  MeasurementType,
  getChartFormFromMeasurementType,
} from "../lib/analytics/main-kpis";
import type { KpiSnapshot } from "../lib/analytics/mock-data";

interface AnalyticsHeroChartProps {
  /**
   * Measurement type determines chart form (ADR-060).
   * Used to select between filled-line, plain-line, bars, and bounded-ratio forms.
   */
  measurementType: MeasurementType;
  label: string;
  snapshot: KpiSnapshot;
  comparePreviousPeriod: boolean;
  /**
   * Deprecated: chartKind is kept for backwards compatibility during transition.
   * When slice #867 retires ChartKind, this prop can be removed and the resolver
   * will be the only decision point for chart appearance.
   */
  chartKind?: ChartKind;
}

export function AnalyticsHeroChart({
  measurementType,
  label,
  snapshot,
  comparePreviousPeriod,
  chartKind,
}: AnalyticsHeroChartProps) {
  const previousData = comparePreviousPeriod
    ? snapshot.previousTimeSeries
    : undefined;

  // For bounded-ratio (e.g., Cancellation rate), check if gaugeValue exists
  // until slice #860/#864 implements the band chart. Fall back to gauge display.
  if (measurementType === "bounded-ratio" && snapshot.gaugeValue !== undefined) {
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

  // Render filled-line form: gradient fill for sum-able quantities (e.g., GMV)
  if (measurementType === "flow") {
    const overlayData = comparePreviousPeriod
      ? previousData
      : snapshot.forecastSeries;

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

  // Render plain-line form: no fill for averages and rates (e.g., AOV, CTOR)
  if (measurementType === "average" || measurementType === "rate") {
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

  // For count (LIVE hours) and bounded-ratio (when band chart is ready),
  // fall back to plain-line until slices #861 and #860/#864 land.
  if (measurementType === "count") {
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

interface AnalyticsUnavailableChartPatternProps {
  label: string;
}

export function AnalyticsUnavailableChartPattern({
  label,
}: AnalyticsUnavailableChartPatternProps) {
  return (
    <div
      aria-hidden="true"
      className="analytics-unavailable-chart analytics-chart-chrome analytics-chart-chrome--empty"
      data-testid="analytics-unavailable-chart"
    >
      <p className="juli-sr-only">{label} — biểu đồ chưa khả dụng</p>
      <svg aria-hidden="true" focusable="false" viewBox="0 0 120 40">
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
