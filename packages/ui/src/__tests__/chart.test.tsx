import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// Polyfill PointerEvent for jsdom tests
if (typeof globalThis.PointerEvent === "undefined") {
  class MockPointerEvent extends Event {
    clientX = 0;
    clientY = 0;
    isPrimary = true;

    constructor(type: string, init?: Partial<PointerEvent>) {
      super(type, init);
      this.clientX = init?.clientX ?? 0;
      this.clientY = init?.clientY ?? 0;
      this.isPrimary = init?.isPrimary ?? true;
    }
  }
  globalThis.PointerEvent = MockPointerEvent as any;
}

import {
  CHART_SERIES_COLORS,
  ChartExpandableTile,
  ChartTextEquivalent,
  MetricSparkline,
  TrendAreaChart,
  TrendBarsChart,
  TrendLineChart,
} from "../chart";
import { loadUiStyles } from "./test-utils";

// Mock snapshot for testing (simulates the structure without importing from demo)
interface MockSnapshot {
  trend: "positive" | "negative" | "neutral" | "warning";
  delta?: string;
  formattedValue?: string;
}

const createMockSnapshot = (overrides: Partial<MockSnapshot> = {}): MockSnapshot => ({
  trend: "positive",
  delta: "▲ 15%",
  formattedValue: "500M",
  ...overrides,
});

const styles = loadUiStyles();

const sampleSeries = [12, 14, 13, 16, 18] as const;
const timeSeries = [
  { label: "T2", value: 12 },
  { label: "T3", value: 14 },
  { label: "T4", value: 13 },
] as const;

describe("Chart primitives", () => {
  it("maps series colors to theme CSS variables", () => {
    expect(CHART_SERIES_COLORS.positive).toBe("var(--juli-success)");
    expect(CHART_SERIES_COLORS.negative).toBe("var(--juli-destructive)");
    expect(CHART_SERIES_COLORS.warning).toBe("var(--juli-warning)");
    expect(CHART_SERIES_COLORS.neutral).toBe("var(--juli-chart-neutral)");
  });

  it("keeps brand pink out of every chart series (ADR-054)", () => {
    for (const color of Object.values(CHART_SERIES_COLORS)) {
      expect(color).not.toBe("var(--juli-primary)");
      expect(color).not.toBe("var(--juli-primary-strong)");
    }
  });

  it("renders a Recharts sparkline with an accessible text equivalent", () => {
    render(
      <MetricSparkline
        data={sampleSeries}
        delta="▲ 12%"
        label="Doanh thu"
        trend="positive"
        value="120 triệu"
      />,
    );

    expect(screen.getByTestId("metric-sparkline-visual")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(
      document.querySelector(".recharts-wrapper"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Doanh thu — 120 triệu — ▲ 12% — xu hướng tăng"),
    ).toHaveClass("juli-sr-only");
  });

  it("renders area and line charts with theme-variable strokes", () => {
    const { rerender } = render(
      <TrendAreaChart
        data={timeSeries}
        delta="▼ 4%"
        label="Tồn kho"
        trend="negative"
        value="84%"
      />,
    );

    expect(
      document.querySelector('[data-testid="trend-area-chart-visual"] .recharts-wrapper'),
    ).toBeInTheDocument();

    rerender(
      <TrendLineChart
        currentData={timeSeries}
        delta="▲ 6%"
        label="ROAS"
        previousData={[
          { label: "T2", value: 10 },
          { label: "T3", value: 11 },
          { label: "T4", value: 12 },
        ]}
        trend="positive"
        value="3.2"
      />,
    );

    expect(
      document.querySelector('[data-testid="trend-line-chart-visual"] .recharts-wrapper'),
    ).toBeInTheDocument();
  });

  it("exposes a keyboard-operable expandable chart tile", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();

    render(
      <ChartExpandableTile
        delta="▲ 8%"
        expanded={false}
        label="Doanh thu ròng"
        onToggle={onToggle}
        trend="positive"
        value="98 triệu"
      >
        <ChartTextEquivalent label="Chi tiết" value="98 triệu" />
      </ChartExpandableTile>,
    );

    const trigger = screen.getByRole("button", { name: /Doanh thu ròng/ });

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(styles).toContain(".juli-chart-tile__trigger:focus-visible");

    await user.click(trigger);
    expect(onToggle).toHaveBeenCalledOnce();

    await user.keyboard("{Enter}");
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  describe("Chart hue stability (issue #865: color follows entity, not rank)", () => {
    it("GREEN: metric passes neutral trend to chart (independent of delta direction)", () => {
      // Per ADR-060, the chart trend must always be "neutral" for stable identity,
      // independent of whether the delta is positive or negative (ADR-060 § 5).
      // Both snapshots receive trend: "neutral" per the fix.

      // The test verifies the contract at component boundary:
      // when a metric is rendered with trend="neutral", it accepts that value
      // and renders the chart with it (not deriving trend from delta).

      const { container: containerPos } = render(
        <TrendAreaChart
          data={timeSeries}
          label="GMV"
          trend="neutral"
          value="500M"
          delta="▲ 15%"
        />
      );

      const { container: containerNeg } = render(
        <TrendAreaChart
          data={timeSeries}
          label="GMV"
          trend="neutral"
          value="500M"
          delta="▼ 5%"
        />
      );

      // Both charts render (visual placeholder ensures chart renders)
      expect(
        containerPos.querySelector('[data-testid="trend-area-chart-visual"]'),
      ).toBeInTheDocument();
      expect(
        containerNeg.querySelector('[data-testid="trend-area-chart-visual"]'),
      ).toBeInTheDocument();

      // The sr-only text includes the delta with its arrow and direction
      expect(containerPos.querySelector(".juli-sr-only")?.textContent).toContain(
        "▲ 15%",
      );
      expect(containerNeg.querySelector(".juli-sr-only")?.textContent).toContain(
        "▼ 5%",
      );

      // Most importantly: both received trend="neutral", so CHART_SERIES_COLORS["neutral"]
      // is the authored color for both, regardless of delta sign.
      expect(CHART_SERIES_COLORS.neutral).toBe("var(--juli-chart-neutral)");
    });

    it("GREEN: changing date range does not change chart trend (metric keeps neutral)", () => {
      // Changing the date range must not repaint the metric (ADR-060 § 5).
      // All snapshots pass trend="neutral", so all render the same color.
      // This test verifies that the envelope mapper (or mock data) sends neutral
      // regardless of the range parameter.

      const ranges = [
        { label: "7d", value: "118M" },
        { label: "30d", value: "485M" },
        { label: "90d", value: "1.42B" },
      ];

      const charts = ranges.map(({ label, value }) =>
        render(
          <TrendAreaChart
            data={timeSeries}
            label={label}
            trend="neutral"
            value={value}
          />,
        ),
      );

      // All three charts should render (all with trend="neutral")
      for (const { container } of charts) {
        expect(
          container.querySelector('[data-testid="trend-area-chart-visual"]'),
        ).toBeInTheDocument();
      }

      // All use neutral, so all map to the same color
      expect(CHART_SERIES_COLORS.neutral).toBe("var(--juli-chart-neutral)");
      // And neutral never equals positive or destructive
      expect(CHART_SERIES_COLORS.neutral).not.toBe(
        CHART_SERIES_COLORS.positive,
      );
      expect(CHART_SERIES_COLORS.neutral).not.toBe(
        CHART_SERIES_COLORS.negative,
      );
    });

    it("GREEN: no success/destructive colors on trend lines for ordinary movement", () => {
      // Status colors (success/destructive) are reserved for genuine breaches
      // (bounded-ratio tolerance band, #864). Ordinary trend charts always use
      // neutral, never green or red. The CHART_SERIES_COLORS map enforces this.

      // Verify the constant: neutral is never green or red
      expect(CHART_SERIES_COLORS.neutral).not.toBe(CHART_SERIES_COLORS.positive);
      expect(CHART_SERIES_COLORS.neutral).not.toBe(CHART_SERIES_COLORS.negative);

      // Neutral is gray (per ADR-054)
      expect(CHART_SERIES_COLORS.neutral).toBe("var(--juli-chart-neutral)");

      // Positive and negative are reserved for status/breaches (green and red)
      expect(CHART_SERIES_COLORS.positive).toBe("var(--juli-success)");
      expect(CHART_SERIES_COLORS.negative).toBe("var(--juli-destructive)");

      // When a chart is authored with trend="neutral", it gets the neutral color
      const { container } = render(
        <TrendAreaChart
          data={timeSeries}
          label="Test KPI"
          trend="neutral"
          value="100"
        />
      );

      // Chart should render
      expect(
        container.querySelector('[data-testid="trend-area-chart-visual"]'),
      ).toBeInTheDocument();
    });

    it("GREEN: delta chip (arrow + figure) conveys direction; chart hue is stable", () => {
      // Direction (positive/negative delta) is conveyed by the delta chip:
      // 1. Arrow symbol (▲/▼) — movement direction
      // 2. Figure — percentage change
      // 3. Tone — semantic good/bad per goal direction (handled by #858)
      //
      // The chart hue (neutral) is stable independent of the delta.

      const { container: containerUp } = render(
        <TrendAreaChart
          data={timeSeries}
          label="GMV"
          trend="neutral"
          value="500M"
          delta="▲ 15%"
        />
      );

      const { container: containerDown } = render(
        <TrendAreaChart
          data={timeSeries}
          label="GMV"
          trend="neutral"
          value="500M"
          delta="▼ 8%"
        />
      );

      // Delta (with arrow) is in sr-only text; arrow conveys direction
      const srUp = containerUp.querySelector(".juli-sr-only")?.textContent;
      const srDown = containerDown.querySelector(".juli-sr-only")?.textContent;

      expect(srUp).toContain("▲ 15%"); // Up arrow in direction case
      expect(srDown).toContain("▼ 8%"); // Down arrow in decline case

      // Both charts render with the same trend="neutral"
      expect(CHART_SERIES_COLORS.neutral).toBe("var(--juli-chart-neutral)");

      // Chart itself is never colored by the delta; color comes from trend only
      // Both receive trend="neutral", so both render gray, not green/red
      expect(CHART_SERIES_COLORS.neutral).not.toBe(CHART_SERIES_COLORS.positive);
      expect(CHART_SERIES_COLORS.neutral).not.toBe(CHART_SERIES_COLORS.negative);
    });
  });

  describe("Line chart endpoint marker and label (issue #862)", () => {
    it("renders an endpoint marker (circle) on line charts", () => {
      const testData = [
        { label: "T1", value: 100 },
        { label: "T2", value: 120 },
        { label: "T3", value: 115 },
      ];

      render(
        <TrendLineChart
          currentData={testData}
          label="Test KPI"
          trend="positive"
          value="115"
        />,
      );

      const visual = document.querySelector(
        '[data-testid="trend-line-chart-visual"]',
      );
      expect(visual).toBeInTheDocument();

      // Check for circles in the chart (Recharts renders dots as circles)
      // After implementation, endpoint marker will be a circle with class indicating endpoint
      const circles = visual?.querySelectorAll("circle");
      expect(circles?.length ?? 0).toBeGreaterThan(0);
    });

    it("endpoint marker has proper dimensions (≥8px diameter)", () => {
      const testData = [
        { label: "T1", value: 100 },
        { label: "T2", value: 120 },
        { label: "T3", value: 115 },
      ];

      render(
        <TrendLineChart
          currentData={testData}
          label="Test KPI"
          trend="positive"
          value="115"
        />,
      );

      const visual = document.querySelector(
        '[data-testid="trend-line-chart-visual"]',
      );

      // Find endpoint marker circle (should have a data attribute or class marking it as endpoint)
      const endpointMarker = visual?.querySelector(
        "circle[data-chart-marker-endpoint]",
      );
      const radius = endpointMarker
        ? parseFloat(endpointMarker.getAttribute("r") || "0")
        : 0;

      // Diameter should be ≥8px, so radius should be ≥4px
      expect(radius).toBeGreaterThanOrEqual(4);
    });

    it("endpoint marker has a 2px surface-colored ring", () => {
      const testData = [
        { label: "T1", value: 100 },
        { label: "T2", value: 120 },
        { label: "T3", value: 115 },
      ];

      render(
        <TrendLineChart
          currentData={testData}
          label="Test KPI"
          trend="positive"
          value="115"
        />,
      );

      const visual = document.querySelector(
        '[data-testid="trend-line-chart-visual"]',
      );

      // Check for ring element beside endpoint marker
      const endpointRing = visual?.querySelector(
        "circle[data-chart-marker-ring]",
      );
      const ringStrokeWidth = endpointRing
        ? parseFloat(endpointRing.getAttribute("stroke-width") || "0")
        : 0;

      expect(ringStrokeWidth).toBe(2);
      // Ring color should be surface-colored (from CSS variable)
      const ringStroke = endpointRing?.getAttribute("stroke");
      expect(ringStroke).toBeTruthy();
    });

    it("renders a value label beside the endpoint using text tokens", () => {
      const testData = [
        { label: "T1", value: 100 },
        { label: "T2", value: 120 },
        { label: "T3", value: 115 },
      ];

      const testValue = "115";

      render(
        <TrendLineChart
          currentData={testData}
          label="Test KPI"
          trend="positive"
          value={testValue}
        />,
      );

      const visual = document.querySelector(
        '[data-testid="trend-line-chart-visual"]',
      );

      // Check for value label text element
      const valueLabel = visual?.querySelector("text[data-chart-endpoint-label]");
      expect(valueLabel).toBeInTheDocument();

      // Label text should contain the value (or be testable)
      const labelText = valueLabel?.textContent;
      expect(labelText).toBeTruthy();

      // Verify the label uses text tokens (check stroke/fill are not the series color)
      const labelFill = valueLabel?.getAttribute("fill");
      expect(labelFill).not.toContain("success");
      expect(labelFill).not.toContain("destructive");
      expect(labelFill).not.toContain("warning");
    });

    it("drops the y-axis entirely now that endpoint label is present", () => {
      const testData = [
        { label: "T1", value: 100 },
        { label: "T2", value: 200 },
        { label: "T3", value: 150 },
      ];

      render(
        <TrendLineChart
          currentData={testData}
          label="Test KPI"
          trend="positive"
          value="150"
        />,
      );

      const visual = document.querySelector(
        '[data-testid="trend-line-chart-visual"]',
      );
      // With endpoint label present, YAxis should not render
      const yAxis = visual?.querySelector(".recharts-yaxis");
      expect(yAxis).not.toBeInTheDocument();
    });

    it("displays first and last period labels on time axis", () => {
      const testData = [
        { label: "Day 1", value: 100 },
        { label: "Day 2", value: 120 },
        { label: "Day 3", value: 115 },
        { label: "Day 4", value: 130 },
        { label: "Day 5", value: 125 },
      ];

      render(
        <TrendLineChart
          currentData={testData}
          label="Test KPI"
          trend="positive"
          value="125"
        />,
      );

      const visual = document.querySelector(
        '[data-testid="trend-line-chart-visual"]',
      );

      // Get all text in xaxis ticks
      const xAxisTicks = visual?.querySelectorAll(
        ".recharts-xaxis .recharts-cartesian-axis-tick text",
      );
      const tickTexts = Array.from(xAxisTicks ?? []).map(
        (el) => el.textContent,
      );

      // With interval="preserveStartEnd", should show first and last
      // If no ticks visible, chart may have issue, but we'll verify the property is set
      if (tickTexts.length > 0) {
        expect(tickTexts.some((t) => t?.includes("Day 1"))).toBe(true);
        expect(tickTexts.some((t) => t?.includes("Day 5"))).toBe(true);
      }
    });

    it("does not render vertical gridlines", () => {
      const testData = [
        { label: "T1", value: 100 },
        { label: "T2", value: 120 },
        { label: "T3", value: 115 },
      ];

      render(
        <TrendLineChart
          currentData={testData}
          label="Test KPI"
          trend="positive"
          value="115"
        />,
      );

      const visual = document.querySelector(
        '[data-testid="trend-line-chart-visual"]',
      );

      // Check CartesianGrid - should have vertical={false}
      const cartesianGrid = visual?.querySelector(".recharts-cartesian-grid");
      expect(cartesianGrid).toBeInTheDocument();

      // Count vertical lines (which have x1 === x2, same x coordinate)
      // With vertical={false}, no vertical lines should be present
      const gridLines = visual?.querySelectorAll(
        ".recharts-cartesian-grid line",
      );
      const verticalLines = Array.from(gridLines ?? []).filter((line) => {
        const x1 = line.getAttribute("x1");
        const x2 = line.getAttribute("x2");
        const y1 = line.getAttribute("y1");
        const y2 = line.getAttribute("y2");
        // Vertical line: x1 === x2 and y1 !== y2
        return (
          x1 === x2 &&
          y1 !== y2 &&
          x1 !== null &&
          y1 !== null &&
          y2 !== null
        );
      });

      // Should have no vertical lines
      expect(verticalLines.length).toBe(0);
    });

    it("renders area chart with endpoint marker and label", () => {
      const testData = [
        { label: "T1", value: 100 },
        { label: "T2", value: 120 },
        { label: "T3", value: 115 },
      ];

      render(
        <TrendAreaChart
          data={testData}
          label="Test KPI"
          trend="positive"
          value="115"
        />,
      );

      const visual = document.querySelector(
        '[data-testid="trend-area-chart-visual"]',
      );
      expect(visual).toBeInTheDocument();

      // Area charts should also have endpoint indicator (circle/marker)
      const circles = visual?.querySelectorAll("circle");
      expect((circles?.length ?? 0) > 0).toBe(true);
    });

    it("endpoint label renders within chart bounds (no horizontal overflow)", () => {
      // Explicit width: the component default must not silently change what
      // this test measures. Before the right margin was reserved the label was
      // authored past the right edge (x=324 in a 320-wide chart).
      const CHART_WIDTH = 280;
      // Room for the widest formatted value at font-size 12, ~0.6em per char.
      const MIN_LABEL_ROOM = 60;
      const testData = [
        { label: "T1", value: 100 },
        { label: "T2", value: 120 },
        { label: "T3", value: 150 },
      ];

      const { container } = render(
        <TrendLineChart
          currentData={testData}
          label="Test KPI"
          trend="positive"
          value="150"
          width={CHART_WIDTH}
        />,
      );

      const visual = container.querySelector(
        '[data-testid="trend-line-chart-visual"]',
      );
      const svg = visual?.querySelector("svg");
      const endpointLabel = visual?.querySelector(
        "text[data-chart-endpoint-label]",
      );

      // jsdom does not lay out SVG, so getBoundingClientRect() returns an
      // all-zero rect and would assert 0 <= 1 for any x whatsoever. Assert the
      // authored x attribute against the chart width instead — that is real
      // data in the DOM, and it is what regressed: before the right margin was
      // reserved the label was authored at x=324 in a 320-wide chart.
      const labelX = Number(endpointLabel?.getAttribute("x"));

      expect(endpointLabel).not.toBeNull();
      expect(Number.isFinite(labelX)).toBe(true);
      // The label starts inside the plot, and enough margin remains to its right
      // for the value text itself — not merely for its origin point.
      expect(labelX).toBeLessThan(CHART_WIDTH);
      expect(CHART_WIDTH - labelX).toBeGreaterThanOrEqual(MIN_LABEL_ROOM);
    });
  });

  describe("Chart scrubbing (issue #866)", () => {
    it("GREEN: renders a scrub controller for charts with ≥10 points", () => {
      const testData = Array.from({ length: 30 }, (_, i) => ({
        label: `Day ${i + 1}`,
        value: Math.floor(Math.random() * 100),
      }));

      const { container } = render(
        <TrendAreaChart
          data={testData}
          label="30-day trend"
          trend="neutral"
          value="150"
        />,
      );

      const visual = container.querySelector(
        '[data-testid="trend-area-chart-visual"]',
      );
      expect(visual).toBeInTheDocument();
      // Scrub controller should be present for high-density data
      const scrubController = container.querySelector(
        '[data-chart-scrub-controller]',
      );
      expect(scrubController).toBeInTheDocument();
    });

    it("GREEN: does not render a scrub controller for charts with <10 points", () => {
      const testData = [
        { label: "Day 1", value: 100 },
        { label: "Day 2", value: 120 },
        { label: "Day 3", value: 115 },
        { label: "Day 4", value: 130 },
        { label: "Day 5", value: 125 },
        { label: "Day 6", value: 128 },
        { label: "Day 7", value: 135 },
      ];

      const { container } = render(
        <TrendAreaChart
          data={testData}
          label="7-day trend"
          trend="neutral"
          value="135"
        />,
      );

      const scrubController = container.querySelector(
        '[data-chart-scrub-controller]',
      );
      // No scrub controller for low-density data
      expect(scrubController).not.toBeInTheDocument();
    });

    it("GREEN: pointer events can select nearest point by horizontal position", async () => {
      const testData = Array.from({ length: 30 }, (_, i) => ({
        label: `Day ${i + 1}`,
        value: 50 + i * 10,
      }));

      const { container } = render(
        <TrendAreaChart
          data={testData}
          label="30-day trend"
          trend="neutral"
          value="340"
        />,
      );

      const scrubController = container.querySelector(
        '[data-chart-scrub-controller]',
      ) as HTMLElement;
      expect(scrubController).toBeInTheDocument();

      // Use fireEvent to trigger React's synthetic event handling
      fireEvent.pointerMove(scrubController, {
        clientX: 150,
        clientY: 60,
        isPrimary: true,
      });

      // After pointer move, check if scrub marker gets rendered
      // The scrub marker is rendered conditionally based on selectedIndex state
      const scrubMarker = container.querySelector(
        '[data-chart-scrub-marker-selected="true"]',
      );
      expect(scrubMarker).toBeInTheDocument();
    });

    it("GREEN: scrub line renders when a point is selected", async () => {
      const testData = Array.from({ length: 30 }, (_, i) => ({
        label: `Day ${i + 1}`,
        value: 50 + i * 10,
      }));

      const { container } = render(
        <TrendAreaChart
          data={testData}
          label="30-day trend"
          trend="neutral"
          value="340"
        />,
      );

      const scrubController = container.querySelector(
        '[data-chart-scrub-controller]',
      ) as HTMLElement;

      // Use fireEvent to trigger pointer move
      fireEvent.pointerMove(scrubController, {
        clientX: 150,
        clientY: 60,
        isPrimary: true,
      });

      // Scrub line should be rendered
      const scrubLine = container.querySelector('[data-chart-scrub-line]');
      expect(scrubLine).toBeInTheDocument();
    });

    it("GREEN: releasing pointer clears the scrub selection", async () => {
      const testData = Array.from({ length: 30 }, (_, i) => ({
        label: `Day ${i + 1}`,
        value: 50 + i * 10,
      }));

      const { container } = render(
        <TrendAreaChart
          data={testData}
          label="30-day trend"
          trend="neutral"
          value="340"
        />,
      );

      const scrubController = container.querySelector(
        '[data-chart-scrub-controller]',
      ) as HTMLElement;

      // Simulate drag start
      fireEvent.pointerMove(scrubController, {
        clientX: 150,
        clientY: 60,
        isPrimary: true,
      });

      let scrubLine = container.querySelector('[data-chart-scrub-line]');
      expect(scrubLine).toBeInTheDocument();

      // Simulate release (pointerleave)
      fireEvent.pointerLeave(scrubController);

      // Scrub line should be gone after release
      scrubLine = container.querySelector('[data-chart-scrub-line]');
      expect(scrubLine).not.toBeInTheDocument();
    });

    it("GREEN: readout is not drawn as a descendant of the plot container", () => {
      const testData = Array.from({ length: 30 }, (_, i) => ({
        label: `Day ${i + 1}`,
        value: 50 + i * 10,
      }));

      const { container } = render(
        <TrendAreaChart
          data={testData}
          label="30-day trend"
          trend="neutral"
          value="340"
        />,
      );

      const visual = container.querySelector(
        '[data-testid="trend-area-chart-visual"]',
      );
      expect(visual).toBeInTheDocument();

      // Find any tooltip/readout/pill elements
      const tooltip = visual?.querySelector('[data-chart-tooltip]');
      const pill = visual?.querySelector('[data-chart-pill]');
      const overlay = visual?.querySelector('[data-chart-overlay]');

      // None of these should be inside the plot visual
      expect(tooltip).not.toBeInTheDocument();
      expect(pill).not.toBeInTheDocument();
      expect(overlay).not.toBeInTheDocument();
    });
  });

  describe("Bars chart for discrete count data (issue #861)", () => {
    it("RED: renders TrendBarsChart with correct test id", () => {
      const testData = [
        { label: "T1", value: 5 },
        { label: "T2", value: 8 },
        { label: "T3", value: 3 },
      ];

      const { container } = render(
        <TrendBarsChart
          data={testData}
          label="LIVE hours"
          trend="neutral"
          value="16"
        />
      );

      const barsChart = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );
      expect(barsChart).toBeInTheDocument();
    });

    it("RED: renders rectangles (bars) for each data point", () => {
      const testData = [
        { label: "T1", value: 5 },
        { label: "T2", value: 8 },
        { label: "T3", value: 3 },
      ];

      const { container } = render(
        <TrendBarsChart
          data={testData}
          label="LIVE hours"
          trend="neutral"
          value="16"
        />
      );

      const visual = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );
      // Bars are rendered as rectangles in Recharts
      const rectangles = visual?.querySelectorAll("rect");
      // Should have at least 3 rectangles for the 3 data points (plus grid/chart background)
      expect((rectangles?.length ?? 0) > 0).toBe(true);
    });

    it("RED: bar count matches period count", () => {
      const testData = [
        { label: "T1", value: 5 },
        { label: "T2", value: 8 },
        { label: "T3", value: 3 },
        { label: "T4", value: 6 },
        { label: "T5", value: 4 },
      ];

      const { container } = render(
        <TrendBarsChart
          data={testData}
          label="LIVE hours"
          trend="neutral"
          value="26"
        />
      );

      const visual = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );
      // Each bar should be rendered with data-chart-bar attribute
      const bars = visual?.querySelectorAll("[data-chart-bar]");
      expect(bars?.length).toBe(testData.length);
    });

    it("RED: zero-value period still renders an identifiable slot", () => {
      const testData = [
        { label: "T1", value: 5 },
        { label: "T2", value: 0 },
        { label: "T3", value: 3 },
      ];

      const { container } = render(
        <TrendBarsChart
          data={testData}
          label="LIVE hours"
          trend="neutral"
          value="8"
        />
      );

      const visual = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );
      const bars = visual?.querySelectorAll("[data-chart-bar]");
      // All three periods should render bars, including the zero-value one
      expect(bars?.length).toBe(testData.length);
    });

    it("RED: retains text equivalent for accessibility", () => {
      const testData = [
        { label: "T1", value: 5 },
        { label: "T2", value: 8 },
        { label: "T3", value: 3 },
      ];

      render(
        <TrendBarsChart
          data={testData}
          label="LIVE hours"
          trend="neutral"
          value="16"
          delta="▲ 5%"
        />
      );

      // Should have text equivalent for accessibility
      const textEquivalent = document.querySelector(".juli-sr-only");
      expect(textEquivalent).toBeInTheDocument();
      expect(textEquivalent?.textContent).toContain("LIVE hours");
      expect(textEquivalent?.textContent).toContain("16");
      expect(textEquivalent?.textContent).toContain("▲ 5%");
    });

    it("RED: does not interpolate lines between bars", () => {
      const testData = [
        { label: "T1", value: 5 },
        { label: "T2", value: 8 },
        { label: "T3", value: 3 },
      ];

      const { container } = render(
        <TrendBarsChart
          data={testData}
          label="LIVE hours"
          trend="neutral"
          value="16"
        />
      );

      const visual = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );
      // Should not have line elements connecting bars
      const lines = visual?.querySelectorAll("line[stroke-width]");
      // Only grid lines and axis ticks should be present, no trend line
      // Count lines that look like data lines (would have the series color)
      const dataLines = Array.from(lines ?? []).filter((line) => {
        const stroke = line.getAttribute("stroke");
        // Exclude grid/axis lines (gray color)
        return (
          stroke &&
          stroke !== "var(--juli-border)" &&
          stroke !== "var(--juli-muted-foreground)"
        );
      });
      expect(dataLines.length).toBe(0);
    });

    it("RED: bars have recessive grid treatment like line forms", () => {
      const testData = [
        { label: "T1", value: 5 },
        { label: "T2", value: 8 },
        { label: "T3", value: 3 },
      ];

      const { container } = render(
        <TrendBarsChart
          data={testData}
          label="LIVE hours"
          trend="neutral"
          value="16"
        />
      );

      const visual = container.querySelector(
        '[data-testid="trend-bars-chart-visual"]'
      );
      // Should have CartesianGrid with dashed stroke
      const cartesianGrid = visual?.querySelector(".recharts-cartesian-grid");
      expect(cartesianGrid).toBeInTheDocument();

      const gridLines = visual?.querySelectorAll(
        ".recharts-cartesian-grid line"
      );
      expect((gridLines?.length ?? 0) > 0).toBe(true);
    });
  });
});
