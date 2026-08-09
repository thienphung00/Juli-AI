"use client";

import { TrendAreaChart } from "@juli/ui";

import type { SupplementaryChartSnapshot } from "../lib/analytics/envelope-mapper";
import { analyticsDeltaClass } from "../lib/analytics/visual-polish";

interface AnalyticsSupplementarySectionsProps {
  charts: readonly SupplementaryChartSnapshot[];
}

export function AnalyticsSupplementarySections({
  charts,
}: AnalyticsSupplementarySectionsProps) {
  if (!charts.length) {
    return null;
  }

  return (
    <div className="analytics-supplementary">
      {charts.map((chart) => (
        <section
          aria-labelledby={`analytics-${chart.envelopeKey}-title`}
          className="analytics-supplementary__section"
          data-testid={`analytics-supplementary-${chart.envelopeKey}`}
          key={chart.envelopeKey}
        >
          <h2
            className="analytics-supplementary__title"
            id={`analytics-${chart.envelopeKey}-title`}
          >
            {chart.label}
          </h2>
          <p className="analytics-supplementary__value">{chart.formattedValue}</p>
          <p className={analyticsDeltaClass(chart.trend)}>{chart.delta}</p>
          <div
            className="analytics-chart-chrome"
            data-testid={`analytics-chart-chrome-${chart.envelopeKey}`}
          >
            <TrendAreaChart
              data={chart.timeSeries}
              delta={chart.delta}
              label={chart.label}
              // Real movement for the text equivalent only (#887); the mark
              // hue stays neutral below.
              movement={chart.movement}
              // Stable identity hue: a mark never carries direction (#865).
              // The delta chip above carries it, via analyticsDeltaClass.
              trend={"neutral"}
              value={chart.formattedValue}
              width={320}
            />
          </div>
          <div className="analytics-supplementary__provenance">
            <p>
              <strong>Nguồn dữ liệu:</strong> {chart.dataSource}
            </p>
            <p>
              <strong>Cập nhật lần cuối:</strong> {chart.lastUpdated}
            </p>
          </div>
        </section>
      ))}
    </div>
  );
}
