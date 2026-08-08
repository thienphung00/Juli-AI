import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MAIN_KPI_DEFINITIONS } from "../../lib/analytics/main-kpis";
import { createMockSnapshot } from "../../lib/analytics/__tests__/fixtures";
import { AnalyticsHeroChart } from "../analytics-charts";

describe("AnalyticsHeroChart (P2-CHART-FORM: measurement type → form)", () => {
  describe("AC3: GMV renders with a gradient fill", () => {
    it("RED: gmv-tiktok (flow) renders TrendAreaChart with fill", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={gmv.measurementType}
          label={gmv.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={gmv.chartKind}
        />
      );

      // TrendAreaChart renders with a test id for the visual
      const areaChart = container.querySelector(
        '[data-testid="trend-area-chart-visual"]'
      );
      expect(areaChart).toBeInTheDocument();
    });
  });

  describe("AC4: AOV renders without a fill", () => {
    it("RED: aov (average) renders TrendLineChart without fill", () => {
      const aov = MAIN_KPI_DEFINITIONS.aov;
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={aov.measurementType}
          label={aov.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={aov.chartKind}
        />
      );

      // TrendLineChart renders with a test id for the visual
      const lineChart = container.querySelector(
        '[data-testid="trend-line-chart-visual"]'
      );
      expect(lineChart).toBeInTheDocument();

      // Should NOT have TrendAreaChart
      const areaChart = container.querySelector(
        '[data-testid="trend-area-chart-visual"]'
      );
      expect(areaChart).not.toBeInTheDocument();
    });
  });

  describe("AC5: CTOR renders without a fill, with a percentage-formatted axis", () => {
    it("RED: ctor (rate) renders TrendLineChart without fill", () => {
      const ctor = MAIN_KPI_DEFINITIONS.ctor;
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={ctor.measurementType}
          label={ctor.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={ctor.chartKind}
        />
      );

      // TrendLineChart renders with a test id for the visual
      const lineChart = container.querySelector(
        '[data-testid="trend-line-chart-visual"]'
      );
      expect(lineChart).toBeInTheDocument();

      // Should NOT have TrendAreaChart (which has fill)
      const areaChart = container.querySelector(
        '[data-testid="trend-area-chart-visual"]'
      );
      expect(areaChart).not.toBeInTheDocument();
    });
  });

  describe("AC8: No declared form produces an empty result", () => {
    it("RED: gmv-tiktok renders some chart element", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={gmv.measurementType}
          label={gmv.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={gmv.chartKind}
        />
      );

      // Should render either an area or line chart
      const chart =
        container.querySelector('[data-testid="trend-area-chart-visual"]') ||
        container.querySelector('[data-testid="trend-line-chart-visual"]');
      expect(chart).toBeInTheDocument();
    });

    it("RED: aov renders some chart element", () => {
      const aov = MAIN_KPI_DEFINITIONS.aov;
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={aov.measurementType}
          label={aov.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={aov.chartKind}
        />
      );

      // Should render either an area or line chart
      const chart =
        container.querySelector('[data-testid="trend-area-chart-visual"]') ||
        container.querySelector('[data-testid="trend-line-chart-visual"]');
      expect(chart).toBeInTheDocument();
    });

    it("RED: ctor renders some chart element", () => {
      const ctor = MAIN_KPI_DEFINITIONS.ctor;
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={ctor.measurementType}
          label={ctor.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={ctor.chartKind}
        />
      );

      // Should render either an area or line chart
      const chart =
        container.querySelector('[data-testid="trend-area-chart-visual"]') ||
        container.querySelector('[data-testid="trend-line-chart-visual"]');
      expect(chart).toBeInTheDocument();
    });
  });
});
