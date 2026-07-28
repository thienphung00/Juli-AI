"use client";

import { TrendAreaChart } from "@juli/ui";

import type { SupplementaryChartSnapshot } from "../lib/analytics/envelope-mapper";

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
            className="analytics-hero__title"
            id={`analytics-${chart.envelopeKey}-title`}
          >
            {chart.label}
          </h2>
          <p className="analytics-hero__value">{chart.formattedValue}</p>
          <p className="analytics-hero__delta">{chart.delta}</p>
          <div className="analytics-hero__chart">
            <TrendAreaChart
              data={chart.timeSeries}
              delta={chart.delta}
              label={chart.label}
              trend={chart.trend}
              value={chart.formattedValue}
              width={320}
            />
          </div>
          <div className="analytics-hero__provenance">
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
