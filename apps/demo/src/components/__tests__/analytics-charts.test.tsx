import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  type UnavailableKpiReason,
  MAIN_KPI_DEFINITIONS,
} from "../../lib/analytics/main-kpis";
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

  describe("AC5: No render path returns null for a declared form", () => {
    it("bounded-ratio with data but no bounded-ratio payload renders explained state, not null", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      // Snapshot exists (data available) but the bounded-ratio payload is absent.
      // This is the regression case: the declared form had no branch to render it
      // and fell through to null, leaving cancellation rate blank.
      const snapshot = createMockSnapshot({
        boundedRatio: undefined,
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={cancellationRate.chartKind}
        />
      );

      // Should render an explained state, not null/blank
      // Criterion 5: "No render path returns null for a declared form"
      const explained = container.querySelector(
        '[data-testid="analytics-unavailable-explained"]'
      );
      expect(explained).toBeInTheDocument();

      // Verify it's not just rendering nothing
      expect(container.innerHTML.length).toBeGreaterThan(0);
    });
  });

  describe("AC6-7: LIVE hours (count) renders as bars, not a line", () => {
    it("RED: live-hours (count) renders TrendBarsChart", () => {
      const liveHours = MAIN_KPI_DEFINITIONS["live-hours"];
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={liveHours.measurementType}
          label={liveHours.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={liveHours.chartKind}
        />
      );

      // TrendBarsChart renders with its test id
      const barsChart = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );
      expect(barsChart).toBeInTheDocument();

      // Should NOT render a line chart
      const lineChart = container.querySelector(
        '[data-testid="trend-line-chart-visual"]'
      );
      expect(lineChart).not.toBeInTheDocument();
    });

    it("RED: live-hours renders bars for each period, not a line", () => {
      const liveHours = MAIN_KPI_DEFINITIONS["live-hours"];
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={liveHours.measurementType}
          label={liveHours.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={liveHours.chartKind}
        />
      );

      const visual = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );

      // Should have bars (rectangles with data-chart-bar)
      const bars = visual?.querySelectorAll("[data-chart-bar]");
      expect((bars?.length ?? 0) > 0).toBe(true);

      // Should not have trend lines connecting bars
      // Count the SVG line elements (excluding grid lines)
      const lines = visual?.querySelectorAll("line[stroke-width]");
      const trendLines = Array.from(lines ?? []).filter((line) => {
        const stroke = line.getAttribute("stroke");
        // Exclude grid/axis visual elements
        return (
          stroke &&
          stroke !== "var(--juli-border)" &&
          stroke !== "var(--juli-muted-foreground)"
        );
      });
      expect(trendLines.length).toBe(0);
    });

    it("RED: bars count matches the period count", () => {
      const liveHours = MAIN_KPI_DEFINITIONS["live-hours"];
      const snapshot = createMockSnapshot();

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={liveHours.measurementType}
          label={liveHours.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={liveHours.chartKind}
        />
      );

      const visual = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );
      const bars = visual?.querySelectorAll("[data-chart-bar]");

      // Should have one bar per period in the time series
      expect(bars?.length).toBe(snapshot.timeSeries.length);
    });
  });

  describe("AC1-2: Unavailable KPI renders explained empty state", () => {
    it("RED: unavailable KPI (null snapshot) renders explained state, not null", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      const unavailableReason: UnavailableKpiReason = {
        dataSource: "TikTok Shop",
        activationRequirement: "Cần kích hoạt TikTok Shop",
      };

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={gmv.measurementType}
          label={gmv.name}
          snapshot={null}
          comparePreviousPeriod={false}
          chartKind={gmv.chartKind}
          unavailableReason={unavailableReason}
        />
      );

      // Should render an unavailable state, not null
      const unavailableState = container.querySelector(
        '[data-testid="analytics-unavailable-explained"]'
      );
      expect(unavailableState).toBeInTheDocument();
    });

    it("RED: unavailable state includes dataSource and activationRequirement", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      const unavailableReason: UnavailableKpiReason = {
        dataSource: "TikTok Shop",
        activationRequirement: "Cần kích hoạt TikTok Shop",
      };

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={gmv.measurementType}
          label={gmv.name}
          snapshot={null}
          comparePreviousPeriod={false}
          chartKind={gmv.chartKind}
          unavailableReason={unavailableReason}
        />
      );

      const unavailableState = container.querySelector(
        '[data-testid="analytics-unavailable-explained"]'
      );
      expect(unavailableState?.textContent).toContain("TikTok Shop");
      expect(unavailableState?.textContent).toContain("Cần kích hoạt TikTok Shop");
    });

    it("RED: unavailable state is accessible (not aria-hidden)", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      const unavailableReason: UnavailableKpiReason = {
        dataSource: "TikTok Shop",
        activationRequirement: "Cần kích hoạt TikTok Shop",
      };

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={gmv.measurementType}
          label={gmv.name}
          snapshot={null}
          comparePreviousPeriod={false}
          chartKind={gmv.chartKind}
          unavailableReason={unavailableReason}
        />
      );

      const unavailableState = container.querySelector(
        '[data-testid="analytics-unavailable-explained"]'
      );
      // Should NOT have aria-hidden="true"
      expect(unavailableState?.getAttribute("aria-hidden")).not.toBe("true");
      // Should be in the document (not hidden to AT)
      expect(unavailableState).toBeInTheDocument();
    });

    it("RED: available and unavailable states have matching layout structure", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      const snapshot = createMockSnapshot();
      const unavailableReason: UnavailableKpiReason = {
        dataSource: "TikTok Shop",
        activationRequirement: "Cần kích hoạt TikTok Shop",
      };

      // Render available state
      const { container: containerAvailable } = render(
        <AnalyticsHeroChart
          measurementType={gmv.measurementType}
          label={gmv.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
          chartKind={gmv.chartKind}
        />
      );

      // Render unavailable state
      const { container: containerUnavailable } = render(
        <AnalyticsHeroChart
          measurementType={gmv.measurementType}
          label={gmv.name}
          snapshot={null}
          comparePreviousPeriod={false}
          chartKind={gmv.chartKind}
          unavailableReason={unavailableReason}
        />
      );

      // Both should render a figure element with consistent structure
      const figureAvailable = containerAvailable.querySelector("figure");
      const figureUnavailable = containerUnavailable.querySelector(
        "figure.analytics-hero-chart--unavailable"
      );

      expect(figureAvailable).toBeInTheDocument();
      expect(figureUnavailable).toBeInTheDocument();

      // Both should have SVG visualizations to occupy similar space
      const svgAvailable = figureAvailable?.querySelector("svg");
      const svgUnavailable = figureUnavailable?.querySelector("svg");

      expect(svgAvailable).toBeInTheDocument();
      expect(svgUnavailable).toBeInTheDocument();

      // Both should have viewBox attributes to scale responsively
      expect(svgUnavailable?.getAttribute("viewBox")).toBeTruthy();
    });
  });
});
