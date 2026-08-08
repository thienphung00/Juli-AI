"use client";

import type { ChartTrend } from "@juli/ui";
import {
  BandedLineChart,
  MetricSparkline,
  ProgressBar,
  TrendAreaChart,
  TrendBarsChart,
  TrendLineChart,
} from "@juli/ui";

import type {
  ChartKind,
  MeasurementType,
  UnavailableKpiReason,
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
  snapshot: KpiSnapshot | null;
  comparePreviousPeriod: boolean;
  /**
   * Deprecated: chartKind is kept for backwards compatibility during transition.
   * When slice #867 retires ChartKind, this prop can be removed and the resolver
   * will be the only decision point for chart appearance.
   */
  chartKind?: ChartKind;
  /**
   * When snapshot is null, provides the reason why the KPI is unavailable
   * (dataSource and activationRequirement). Used to render an explained empty state.
   */
  unavailableReason?: UnavailableKpiReason;
}

export function AnalyticsHeroChart({
  measurementType,
  label,
  snapshot,
  comparePreviousPeriod,
  chartKind,
  unavailableReason,
}: AnalyticsHeroChartProps) {
  // Handle unavailable KPI: render explained state instead of null
  if (!snapshot) {
    return (
      <AnalyticsUnavailableExplainedChart
        label={label}
        unavailableReason={unavailableReason}
      />
    );
  }

  const previousData = comparePreviousPeriod
    ? snapshot.previousTimeSeries
    : undefined;

  // Exhaustive switch on measurement type ensures every declared form renders
  // either its proper chart or an explained state — never null (ADR-060).
  switch (measurementType) {
    case "flow": {
      // Render filled-line form: gradient fill for sum-able quantities (e.g., GMV)
      const overlayData = comparePreviousPeriod
        ? previousData
        : snapshot.forecastSeries;

      return (
        <TrendAreaChart
          data={snapshot.timeSeries}
          delta={snapshot.delta}
          label={label}
          trend={"neutral" as ChartTrend}
          value={snapshot.formattedValue}
          width={320}
        />
      );
    }

    case "average":
    case "rate": {
      // Render plain-line form: no fill for averages and rates (e.g., AOV, CTOR)
      const overlayData = comparePreviousPeriod
        ? previousData
        : snapshot.forecastSeries;

      return (
        <TrendLineChart
          currentData={snapshot.timeSeries}
          delta={snapshot.delta}
          label={label}
          previousData={overlayData}
          trend={"neutral"}
          value={snapshot.formattedValue}
          width={320}
        />
      );
    }

    case "count": {
      // Render bars form for discrete counts (LIVE hours).
      // Counts are individual per-period quantities; bars show each period distinctly
      // without implying interpolation between periods (ADR-060, issue #861).
      return (
        <TrendBarsChart
          data={snapshot.timeSeries}
          delta={snapshot.delta}
          label={label}
          trend={"neutral"}
          value={snapshot.formattedValue}
          width={320}
        />
      );
    }

    case "bounded-ratio": {
      // Bounded-ratio (e.g., Cancellation rate) renders as a banded trend showing
      // the actual series against its tolerance threshold (ADR-060). #860 supplies
      // the boundedRatio payload with value, target, bounds, and tolerance state.
      if (snapshot.boundedRatio) {
        return (
          <BandedLineChart
            data={snapshot.timeSeries}
            label={label}
            value={snapshot.formattedValue}
            target={snapshot.boundedRatio.target}
            bounds={snapshot.boundedRatio.bounds}
            withinTolerance={snapshot.boundedRatio.withinTolerance}
            delta={snapshot.delta}
            width={320}
          />
        );
      }

      // Bounded-ratio with no payload: render explained state, not null (criterion 5)
      return (
        <AnalyticsUnavailableExplainedChart
          label={label}
          unavailableReason={unavailableReason}
        />
      );
    }
  }
}

interface AnalyticsPreviewChartProps {
  label: string;
  sparkline: readonly number[];
  value: string;
  delta: string;
}

export function AnalyticsPreviewChart({
  label,
  sparkline,
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
        trend={"neutral"}
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

interface AnalyticsUnavailableExplainedChartProps {
  label: string;
  unavailableReason?: UnavailableKpiReason;
}

/**
 * Render an explained empty state for an unavailable KPI in the chart's footprint.
 * Provides the dataSource and activationRequirement to help the seller understand
 * why the KPI is unavailable and what would make it available.
 * ADR-060: "When a KPI has no data, render a labelled empty state in the chart's
 * own footprint: the reason it is unavailable and what would make it available."
 */
export function AnalyticsUnavailableExplainedChart({
  label,
  unavailableReason,
}: AnalyticsUnavailableExplainedChartProps) {
  return (
    <figure
      className="analytics-hero-chart analytics-hero-chart--unavailable"
      data-testid="analytics-unavailable-explained"
    >
      <figcaption className="analytics-hero-chart__unavailable-caption">
        <h3 className="analytics-hero-chart__unavailable-title">{label}</h3>
        <p className="analytics-hero-chart__unavailable-reason">
          Chưa khả dụng
        </p>
        {unavailableReason?.dataSource && (
          <p className="analytics-hero-chart__unavailable-detail">
            <strong>Nguồn dữ liệu:</strong> {unavailableReason.dataSource}
          </p>
        )}
        {unavailableReason?.activationRequirement && (
          <p className="analytics-hero-chart__unavailable-detail">
            <strong>Để sử dụng:</strong> {unavailableReason.activationRequirement}
          </p>
        )}
      </figcaption>
      <svg
        aria-hidden="true"
        className="analytics-hero-chart__unavailable-visual"
        focusable="false"
        viewBox="0 0 320 160"
      >
        <line
          stroke="var(--juli-border)"
          strokeDasharray="4 4"
          x1="0"
          x2="320"
          y1="80"
          y2="80"
        />
        <line
          stroke="var(--juli-border)"
          strokeDasharray="2 6"
          x1="0"
          x2="320"
          y1="32"
          y2="32"
        />
        <line
          stroke="var(--juli-border)"
          strokeDasharray="2 6"
          x1="0"
          x2="320"
          y1="128"
          y2="128"
        />
      </svg>
    </figure>
  );
}
