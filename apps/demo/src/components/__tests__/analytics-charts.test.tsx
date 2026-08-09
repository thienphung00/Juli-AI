import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GMV_TIKTOK_ENVELOPE_KEY } from "@juli/contracts";

import {
  type UnavailableKpiReason,
  MAIN_KPI_DEFINITIONS,
} from "../../lib/analytics/main-kpis";
import { buildLiveKpiSnapshot } from "../../lib/analytics/envelope-mapper";
import {
  createMockDemoAnalyticsEnvelope,
  createMockSnapshot,
} from "../../lib/analytics/__tests__/fixtures";
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
        />
      );

      // Render unavailable state
      const { container: containerUnavailable } = render(
        <AnalyticsHeroChart
          measurementType={gmv.measurementType}
          label={gmv.name}
          snapshot={null}
          comparePreviousPeriod={false}
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

  describe("AC9: bounded-ratio renders as a banded trend, not a meter", () => {
    it("RED: cancellation-rate (bounded-ratio) renders BandedLineChart", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        boundedRatio: {
          value: 3.5,
          target: 3.0,
          bounds: { min: 0, max: 10 },
          withinTolerance: false,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      // BandedLineChart renders with its test id
      const bandedChart = container.querySelector(
        '[data-testid="banded-line-chart-visual"]'
      );
      expect(bandedChart).toBeInTheDocument();
    });

    it("RED: tolerance band renders across the plot width", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        boundedRatio: {
          value: 3.5,
          target: 3.0,
          bounds: { min: 0, max: 10 },
          withinTolerance: false,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      // The band is rendered as a rectangle with the tolerance bounds
      const visual = container.querySelector(
        '[data-testid="banded-line-chart-visual"]'
      );
      const band = visual?.querySelector("[data-chart-tolerance-band]");
      expect(band).toBeInTheDocument();
    });

    it("RED: target line renders as a dotted reference line with label", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        boundedRatio: {
          value: 3.5,
          target: 3.0,
          bounds: { min: 0, max: 10 },
          withinTolerance: false,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      const visual = container.querySelector(
        '[data-testid="banded-line-chart-visual"]'
      );
      // Target line should be rendered (either as a line or a reference line)
      const targetLine = visual?.querySelector("[data-chart-target-line]");
      expect(targetLine).toBeInTheDocument();

      // Should have a label for the target
      const targetLabel = visual?.querySelector("[data-chart-target-label]");
      expect(targetLabel).toBeInTheDocument();
    });

    it("RED: series line renders over the band with endpoint marker", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        boundedRatio: {
          value: 3.5,
          target: 3.0,
          bounds: { min: 0, max: 10 },
          withinTolerance: false,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      const visual = container.querySelector(
        '[data-testid="banded-line-chart-visual"]'
      );
      // Series line is rendered as part of the chart
      const seriesLine = visual?.querySelector("svg line");
      expect(seriesLine).toBeInTheDocument();

      // Should have an endpoint marker
      const marker = visual?.querySelector("[data-chart-marker-endpoint]");
      expect(marker).toBeInTheDocument();
    });

    it("RED: value within tolerance renders with neutral hue", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        boundedRatio: {
          value: 2.5,
          target: 3.0,
          bounds: { min: 0, max: 10 },
          withinTolerance: true,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      const visual = container.querySelector(
        '[data-testid="banded-line-chart-visual"]'
      );
      // When within tolerance, series should use neutral hue
      const seriesLine = visual?.querySelector(
        "[data-chart-series-line]"
      );
      expect(seriesLine?.getAttribute("stroke")).toBe("var(--juli-chart-neutral)");
    });

    it("RED: value outside tolerance renders with status palette color", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        boundedRatio: {
          value: 6.5,
          target: 3.0,
          bounds: { min: 0, max: 10 },
          withinTolerance: false,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      const visual = container.querySelector(
        '[data-testid="banded-line-chart-visual"]'
      );
      // When outside tolerance, band should render with status color
      const band = visual?.querySelector("[data-chart-tolerance-band]");
      const fill = band?.getAttribute("fill");
      // Should be destructive color or a status palette color
      expect(fill).toContain("destructive");
    });

    it("RED: y-scale uses bounds from payload, not data range", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        timeSeries: [
          { label: "T1", value: 2.0 },
          { label: "T2", value: 3.0 },
          { label: "T3", value: 2.5 },
        ],
        boundedRatio: {
          value: 2.5,
          target: 3.0,
          bounds: { min: 0, max: 100 }, // Much larger than the data range
          withinTolerance: true,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      const visual = container.querySelector(
        '[data-testid="banded-line-chart-visual"]'
      );
      // The Y-axis should reflect the bounds, not the data
      const yAxis = visual?.querySelector("[data-chart-y-axis]");
      expect(yAxis).toBeInTheDocument();
      // Check that the domain reflects the bounds
      expect(yAxis?.getAttribute("data-domain-min")).toBe("0");
      expect(yAxis?.getAttribute("data-domain-max")).toBe("100");
    });

    it("RED: text equivalent includes value, target, and tolerance state", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        formattedValue: "3.5%",
        boundedRatio: {
          value: 3.5,
          target: 3.0,
          bounds: { min: 0, max: 10 },
          withinTolerance: false,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      // Screen reader text should mention the value and tolerance state
      const srText = container.querySelector(".juli-sr-only");
      expect(srText?.textContent).toContain("3.5%"); // formatted value
      expect(srText?.textContent).toContain("3.0"); // target
      // Should indicate whether within/outside tolerance
      const tolerance = srText?.textContent?.includes("tolerance") ||
                       srText?.textContent?.includes("Ngoài");
      expect(tolerance).toBe(true);
    });

    it("MUTATION: removing the tolerance band should fail the band-exists test", () => {
      const cancellationRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      const snapshot = createMockSnapshot({
        boundedRatio: {
          value: 3.5,
          target: 3.0,
          bounds: { min: 0, max: 10 },
          withinTolerance: false,
        },
      });

      const { container } = render(
        <AnalyticsHeroChart
          measurementType={cancellationRate.measurementType}
          label={cancellationRate.name}
          snapshot={snapshot}
          comparePreviousPeriod={false}
        />
      );

      // This test verifies that the band element is actually rendered
      // If we remove the band in the implementation, this should fail
      const band = container.querySelector("[data-chart-tolerance-band]");
      expect(band).toBeInTheDocument();
    });
  });
});

describe("#865 sweep: no mark carries direction", () => {
  it("every chart mark in the Analytics surface receives the neutral identity hue", async () => {
    // Guards the gap the original sweep missed: the hero chart was fixed while
    // the supplementary section still passed a goal-aware tone into its mark,
    // so those series kept repainting green/red with performance.
    const { readFileSync } = await import("node:fs");
    const sources = [
      "src/components/analytics-charts.tsx",
      "src/components/analytics-supplementary-sections.tsx",
      "src/components/analytics-kpi-card.tsx",
    ];

    const directional: string[] = [];
    for (const file of sources) {
      const text = readFileSync(file, "utf8");
      for (const [index, line] of text.split("\n").entries()) {
        // A mark's trend prop bound to anything other than a literal "neutral"
        // is a directional hue. The delta chip uses analyticsDeltaClass(), not
        // a trend prop, so it is unaffected by this rule.
        if (/^\s*trend=\{(?!"neutral")/.test(line)) {
          directional.push(`${file}:${index + 1} ${line.trim()}`);
        }
      }
    }

    expect(directional).toEqual([]);
  });
});

describe("#887: the accessible sentence states real movement (rise/fall/flat × goal direction)", () => {
  // End-to-end through the single goal-direction resolver: envelope series →
  // buildLiveKpiSnapshot (delta sign × MAIN_KPI_DEFINITIONS.goalDirection) →
  // AnalyticsHeroChart → rendered .juli-sr-only paragraph.
  const buildEnvelopeWith = (
    envelopeKey: string,
    values: readonly number[],
  ) => {
    const base = createMockDemoAnalyticsEnvelope();
    return createMockDemoAnalyticsEnvelope({
      kpis: {
        ...base.kpis,
        [envelopeKey]: {
          ...base.kpis[envelopeKey]!,
          series: values.map((v, index) => ({
            t: `2026-07-${String(index + 1).padStart(2, "0")}`,
            v,
          })),
        },
      },
    });
  };

  const heroSrText = (
    metricKey: "gmv-tiktok" | "cancellation-rate",
    envelopeKey: string,
    values: readonly number[],
  ) => {
    const definition = MAIN_KPI_DEFINITIONS[metricKey];
    const envelope = buildEnvelopeWith(envelopeKey, values);
    const snapshot = buildLiveKpiSnapshot(envelope, metricKey, "30d");
    expect(snapshot).not.toBeNull();

    const { container, unmount } = render(
      <AnalyticsHeroChart
        measurementType={definition.measurementType}
        label={definition.name}
        snapshot={snapshot}
        comparePreviousPeriod={false}
      />
    );
    const text = container.querySelector(".juli-sr-only")?.textContent ?? "";
    unmount();
    return text;
  };

  it("higher-is-better rise: GMV rising says it rose, and is positive", () => {
    const text = heroSrText("gmv-tiktok", GMV_TIKTOK_ENVELOPE_KEY, [420_000_000, 485_000_000]);
    expect(text).toContain("xu hướng tăng — tích cực");
    expect(text).not.toContain("ổn định");
  });

  it("higher-is-better fall: GMV falling says it fell, and needs attention", () => {
    const text = heroSrText("gmv-tiktok", GMV_TIKTOK_ENVELOPE_KEY, [485_000_000, 420_000_000]);
    expect(text).toContain("xu hướng giảm — cần chú ý");
    expect(text).not.toContain("ổn định");
  });

  it("higher-is-better flat: GMV unchanged says it is stable, with no qualifier", () => {
    const text = heroSrText("gmv-tiktok", GMV_TIKTOK_ENVELOPE_KEY, [485_000_000, 485_000_000]);
    expect(text).toContain("xu hướng ổn định");
    expect(text).not.toContain("tích cực");
    expect(text).not.toContain("cần chú ý");
  });

  it("lower-is-better rise: rising cancellations say they rose and need attention — never described as good", () => {
    const text = heroSrText("cancellation-rate", "cancellation_rate", [2.5, 3.5]);
    expect(text).toContain("xu hướng tăng — cần chú ý");
    expect(text).not.toContain("tích cực");
    expect(text).not.toContain("ổn định");
  });

  it("lower-is-better fall: falling cancellations say they fell, and are positive", () => {
    const text = heroSrText("cancellation-rate", "cancellation_rate", [2.5, 1.8]);
    expect(text).toContain("xu hướng giảm — tích cực");
    expect(text).not.toContain("ổn định");
  });

  it("lower-is-better flat: unchanged cancellations say they are stable, with no qualifier", () => {
    const text = heroSrText("cancellation-rate", "cancellation_rate", [2.5, 2.5]);
    expect(text).toContain("xu hướng ổn định");
    expect(text).not.toContain("tích cực");
    expect(text).not.toContain("cần chú ý");
  });
});
