import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  MAIN_KPI_DEFINITIONS,
  getChartFormFromMeasurementType,
} from "../../lib/analytics/main-kpis";
import type { BoundedRatio } from "../../lib/analytics/mock-data";
import { createMockDemoAnalyticsEnvelope } from "../../lib/analytics/__tests__/fixtures";
import { AnalyticsKpiCard } from "../analytics-kpi-card";
import { AnalyticsPreviewChart } from "../analytics-charts";

// #885 (P2-CHART-PREVIEW): the selector-card preview derives its mark from the
// KPI's measurementType through the same resolver as the hero (ADR-060), and
// each resolved form is structurally distinguishable from a horizontal rule.
// jsdom does no SVG layout, so all assertions are structural DOM assertions.

const sparkline = [12, 14, 13, 16, 18] as const;

const withinToleranceRatio: BoundedRatio = {
  value: 1.8,
  target: 3,
  bounds: { min: 0, max: 10 },
  withinTolerance: true,
};

function renderPreview(
  metricKey: keyof typeof MAIN_KPI_DEFINITIONS,
  overrides: { sparkline?: readonly number[]; boundedRatio?: BoundedRatio } = {},
) {
  const definition = MAIN_KPI_DEFINITIONS[metricKey];
  return render(
    <AnalyticsPreviewChart
      boundedRatio={overrides.boundedRatio}
      delta="▲ 8%"
      label={definition.name}
      measurementType={definition.measurementType}
      movement={{ direction: "up", assessment: "favorable" }}
      sparkline={overrides.sparkline ?? sparkline}
      value="123"
    />,
  );
}

describe("AnalyticsPreviewChart (#885: preview form follows measurement type)", () => {
  it("resolves every preview mark through getChartFormFromMeasurementType — no second mapping", async () => {
    const { readFileSync } = await import("node:fs");
    const source = readFileSync("src/components/analytics-charts.tsx", "utf8");

    // The preview switches on the resolver's output, not on measurementType.
    expect(source).toContain("getChartFormFromMeasurementType(measurementType)");
    // The resolver stays a value import from main-kpis — not re-declared here.
    expect(source).not.toMatch(/function\s+getChartFormFromMeasurementType/);
  });

  it("gmv-tiktok (flow) previews as a filled line", () => {
    const { container } = renderPreview("gmv-tiktok");

    const visual = container.querySelector('[data-testid="metric-sparkline-preview"]');
    expect(visual).toHaveAttribute("data-preview-form", "filled-line");
    expect(container.querySelector("polyline[data-preview-line]")).toBeInTheDocument();
    expect(container.querySelector("path[data-preview-fill]")).toBeInTheDocument();
  });

  it("aov (average) previews as a plain line without fill", () => {
    const { container } = renderPreview("aov");

    expect(
      container.querySelector('[data-testid="metric-sparkline-preview"]'),
    ).toHaveAttribute("data-preview-form", "plain-line");
    expect(container.querySelector("polyline[data-preview-line]")).toBeInTheDocument();
    expect(container.querySelector("[data-preview-fill]")).toBeNull();
  });

  it("ctor (rate) previews as a plain line without fill", () => {
    const { container } = renderPreview("ctor");

    expect(
      container.querySelector('[data-testid="metric-sparkline-preview"]'),
    ).toHaveAttribute("data-preview-form", "plain-line");
    expect(container.querySelector("polyline[data-preview-line]")).toBeInTheDocument();
    expect(container.querySelector("[data-preview-fill]")).toBeNull();
  });

  it("live-hours (count) previews as bars, never a continuous line", () => {
    const counts = [6, 8, 0, 10, 7] as const;
    const { container } = renderPreview("live-hours", { sparkline: counts });

    expect(
      container.querySelector('[data-testid="metric-sparkline-preview"]'),
    ).toHaveAttribute("data-preview-form", "bars");
    expect(container.querySelectorAll("rect[data-preview-bar]")).toHaveLength(
      counts.length,
    );
    // Structurally not a continuous line: no polyline and no path anywhere.
    expect(container.querySelector("polyline")).toBeNull();
    expect(container.querySelector("path")).toBeNull();
  });

  it("cancellation-rate (bounded-ratio) previews with its target rendered", () => {
    const { container } = renderPreview("cancellation-rate", {
      sparkline: [2.5, 2.8, 2.2, 1.8],
      boundedRatio: withinToleranceRatio,
    });

    expect(
      container.querySelector('[data-testid="metric-sparkline-preview"]'),
    ).toHaveAttribute("data-preview-form", "bounded-ratio");
    expect(container.querySelector("line[data-preview-target]")).toBeInTheDocument();
    expect(container.querySelector("polyline[data-preview-line]")).toBeInTheDocument();
  });

  it("cancellation-rate without a threshold payload falls back to the neutral unavailable motif rather than a target-less line", () => {
    const { container } = renderPreview("cancellation-rate", {
      sparkline: [2.5, 2.8, 2.2, 1.8],
    });

    expect(container.querySelector("[data-preview-line]")).toBeNull();
    expect(
      container.querySelector('[data-testid="analytics-unavailable-chart"]'),
    ).toBeInTheDocument();
  });

  it("previews are structurally distinguishable from a horizontal rule at 375px", () => {
    // A horizontal rule is a single stroke at one vertical position. Each
    // resolved form breaks that: line forms span the amplitude band, bars are
    // discrete rects, bounded-ratio adds a second (dashed) line character.
    const { container } = renderPreview("aov", {
      sparkline: [420, 485, 460, 510],
    });

    const points = (
      container
        .querySelector("polyline[data-preview-line]")
        ?.getAttribute("points") ?? ""
    )
      .trim()
      .split(/\s+/)
      .map((pair) => Number(pair.split(",")[1]));

    expect(new Set(points).size).toBeGreaterThan(1);
    // Amplitude band span at the default 40px preview height (#924): 40 − 2·3.
    expect(Math.max(...points) - Math.min(...points)).toBeCloseTo(34, 5);
  });

  it("keeps the neutral identity hue; no status color without a genuine breach", () => {
    for (const metricKey of ["gmv-tiktok", "aov", "ctor", "live-hours"] as const) {
      const { container, unmount } = renderPreview(metricKey);
      expect(container.innerHTML).not.toContain("var(--juli-success)");
      expect(container.innerHTML).not.toContain("var(--juli-destructive)");
      expect(container.innerHTML).toContain("var(--juli-chart-neutral)");
      unmount();
    }

    const { container } = renderPreview("cancellation-rate", {
      sparkline: [2.5, 2.8, 2.2, 1.8],
      boundedRatio: withinToleranceRatio,
    });
    expect(container.innerHTML).not.toContain("var(--juli-success)");
    expect(container.innerHTML).not.toContain("var(--juli-destructive)");
  });

  it("marks a genuine breach on the threshold indicator only — the series stays neutral", () => {
    const { container } = renderPreview("cancellation-rate", {
      sparkline: [2.5, 3.1, 3.6, 4.2],
      boundedRatio: {
        value: 4.2,
        target: 3,
        bounds: { min: 0, max: 10 },
        withinTolerance: false,
      },
    });

    expect(
      container.querySelector("line[data-preview-target]"),
    ).toHaveAttribute("stroke", "var(--juli-destructive)");
    expect(
      container.querySelector("polyline[data-preview-line]"),
    ).toHaveAttribute("stroke", "var(--juli-chart-neutral)");
  });

  it("every preview retains its text equivalent inside an aria-hidden wrapper", () => {
    const { container } = renderPreview("gmv-tiktok");

    const wrapper = container.querySelector(".analytics-kpi-card__preview");
    expect(wrapper).toHaveAttribute("aria-hidden", "true");
    const textEquivalent = container.querySelector(".juli-sr-only");
    expect(textEquivalent).toHaveTextContent(
      `${MAIN_KPI_DEFINITIONS["gmv-tiktok"].name} — 123 — ▲ 8%`,
    );
  });

  it("does not hardcode a fixed pixel width/height at the call site (#924)", () => {
    // Regression guard for the defect: literal width={96} height={32} passed
    // at both AnalyticsPreviewChart branches produced a 96×32 mark inside a
    // fluid, full-width card container (341px at 375px viewport). Neither
    // call site should thread a fixed width/height anymore — the preview's
    // own default (fluid width, 40px height) should carry through.
    for (const metricKey of ["gmv-tiktok", "cancellation-rate"] as const) {
      const { container, unmount } = renderPreview(metricKey, {
        sparkline: [2.5, 2.8, 2.2, 1.8],
        boundedRatio: metricKey === "cancellation-rate" ? withinToleranceRatio : undefined,
      });

      const svg = container.querySelector('[data-testid="metric-sparkline-preview"]');
      expect(svg).toHaveAttribute("width", "100%");
      expect(svg).toHaveAttribute("height", "40");
      unmount();
    }
  });

  it("previews carry no tooltip, comparison overlay, endpoint marker, or focus stop", () => {
    const { container } = renderPreview("cancellation-rate", {
      sparkline: [2.5, 2.8, 2.2, 1.8],
      boundedRatio: withinToleranceRatio,
    });

    expect(container.querySelector("[data-chart-endpoint-label]")).toBeNull();
    expect(container.querySelector("[data-chart-marker-endpoint]")).toBeNull();
    expect(container.querySelector("[data-chart-scrub-controller]")).toBeNull();
    expect(container.querySelector("[tabindex]")).toBeNull();
    expect(container.querySelector("svg")).toHaveAttribute("focusable", "false");
  });
});

describe("AnalyticsKpiCard threads measurement type into its preview (#885)", () => {
  const envelope = createMockDemoAnalyticsEnvelope();

  it("cancellation-rate card renders a bounded-ratio preview with its target", () => {
    const { container } = render(
      <AnalyticsKpiCard
        envelope={envelope}
        metricKey="cancellation-rate"
        range="7d"
      />,
    );

    expect(
      container.querySelector('[data-testid="metric-sparkline-preview"]'),
    ).toHaveAttribute("data-preview-form", "bounded-ratio");
    expect(container.querySelector("line[data-preview-target]")).toBeInTheDocument();
  });

  it("live-hours card renders a bars preview, not a line", () => {
    const { container } = render(
      <AnalyticsKpiCard envelope={envelope} metricKey="live-hours" range="7d" />,
    );

    expect(
      container.querySelector('[data-testid="metric-sparkline-preview"]'),
    ).toHaveAttribute("data-preview-form", "bars");
    expect(
      container.querySelectorAll("rect[data-preview-bar]").length,
    ).toBeGreaterThan(0);
    expect(container.querySelector("polyline")).toBeNull();
  });

  it("aov card resolves through the same resolver the hero uses", () => {
    const { container } = render(
      <AnalyticsKpiCard envelope={envelope} metricKey="aov" range="7d" />,
    );

    expect(
      container.querySelector('[data-testid="metric-sparkline-preview"]'),
    ).toHaveAttribute(
      "data-preview-form",
      getChartFormFromMeasurementType(MAIN_KPI_DEFINITIONS.aov.measurementType),
    );
  });
});
