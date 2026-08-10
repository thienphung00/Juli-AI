import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricSparklinePreview } from "../chart";

// Fluid-width, 40px-tall selector-card preview (#885, ADR-060; sizing per
// #924/DEMO-PREVIEW-SCALE): the mark is a simplified, low-contrast member of
// the hero's graph family. jsdom performs no SVG layout — its
// getBoundingClientRect() is an all-zero rect regardless of what actually
// renders — so geometry assertions here are structural: authored SVG
// attributes (points, y1/y2, viewBox, width) and DOM structure, never
// getBoundingClientRect. The internal viewBox coordinate width defaults to
// 96 (see chart.tsx); the rendered pixel width is driven by CSS
// (width="100%") and is asserted separately below.

const series = [10, 20, 15, 30] as const;

function parsePoints(points: string): { x: number; y: number }[] {
  return points
    .trim()
    .split(/\s+/)
    .map((pair) => {
      const [x, y] = pair.split(",");
      return { x: Number(x), y: Number(y) };
    });
}

describe("MetricSparklinePreview (#885: card preview mark treatment)", () => {
  it("filled-line renders a continuous line plus a low-opacity area silhouette", () => {
    const { container } = render(
      <MetricSparklinePreview
        data={series}
        delta="▲ 15%"
        form="filled-line"
        label="GMV TikTok"
        value="485 triệu"
      />,
    );

    const line = container.querySelector("polyline[data-preview-line]");
    const fill = container.querySelector("path[data-preview-fill]");
    expect(line).toBeInTheDocument();
    expect(fill).toBeInTheDocument();
    expect(fill).toHaveAttribute("fill", "var(--juli-chart-neutral)");
    expect(Number(fill?.getAttribute("fill-opacity"))).toBeLessThanOrEqual(0.2);
  });

  it("plain-line renders the line only — no fill silhouette", () => {
    const { container } = render(
      <MetricSparklinePreview
        data={series}
        delta="▲ 4%"
        form="plain-line"
        label="AOV"
        value="500.000 ₫"
      />,
    );

    expect(
      container.querySelector("polyline[data-preview-line]"),
    ).toBeInTheDocument();
    expect(container.querySelector("[data-preview-fill]")).toBeNull();
  });

  it("line marks are min–max normalized to span the amplitude band, so the preview cannot read as a hairline rule", () => {
    const { container } = render(
      <MetricSparklinePreview
        data={series}
        form="plain-line"
        label="AOV"
        value="500.000 ₫"
      />,
    );

    const points = parsePoints(
      container
        .querySelector("polyline[data-preview-line]")
        ?.getAttribute("points") ?? "",
    );
    expect(points).toHaveLength(series.length);

    const ys = points.map((point) => point.y);
    // Band is [3, 37] at the default 40px height (#924): the series minimum
    // sits at the bottom of the band and the maximum at the top.
    expect(Math.max(...ys)).toBeCloseTo(37, 5);
    expect(Math.min(...ys)).toBeCloseTo(3, 5);
    // More than one distinct vertical position — structurally not a rule.
    expect(new Set(ys).size).toBeGreaterThan(1);
  });

  it("bars renders one zero-baselined rect per period and no continuous line", () => {
    const counts = [6, 0, 10, 8] as const;
    const { container } = render(
      <MetricSparklinePreview
        data={counts}
        delta="▲ 2 giờ"
        form="bars"
        label="LIVE hours"
        value="10 giờ"
      />,
    );

    const bars = container.querySelectorAll("rect[data-preview-bar]");
    expect(bars).toHaveLength(counts.length);
    expect(container.querySelector("polyline")).toBeNull();
    expect(container.querySelector("path")).toBeNull();

    for (const bar of bars) {
      // Every bar anchors to the zero baseline (bottom edge of the 40px mark).
      const y = Number(bar.getAttribute("y"));
      const barHeight = Number(bar.getAttribute("height"));
      expect(y + barHeight).toBeCloseTo(40, 5);
      // A zero-value period keeps an identifiable ≥1px slot.
      expect(barHeight).toBeGreaterThanOrEqual(1);
      expect(bar).toHaveAttribute("fill", "var(--juli-chart-neutral)");
    }
  });

  it("bounded-ratio renders a dashed target reference line at the target's position on the fixed bounds scale", () => {
    const { container } = render(
      <MetricSparklinePreview
        boundedRatio={{
          target: 3,
          bounds: { min: 0, max: 10 },
          withinTolerance: true,
        }}
        data={[2.5, 2.8, 2.2, 1.8]}
        delta="▼ 0,7%"
        form="bounded-ratio"
        label="Tỷ lệ hủy đơn"
        value="1,8%"
      />,
    );

    const target = container.querySelector("line[data-preview-target]");
    expect(target).toBeInTheDocument();
    expect(target).toHaveAttribute("stroke-dasharray");
    expect(target).toHaveAttribute("vector-effect", "non-scaling-stroke");
    // Bounds [0, 10] map to the [37, 3] band at the default 40px height
    // (#924); target 3 → 37 − 0.3·34 = 26.8.
    expect(Number(target?.getAttribute("y1"))).toBeCloseTo(26.8, 5);
    expect(Number(target?.getAttribute("y2"))).toBeCloseTo(26.8, 5);

    // The series stays on the same fixed scale (not min–max amplified), so the
    // spatial relation between series and threshold is honest.
    const points = parsePoints(
      container
        .querySelector("polyline[data-preview-line]")
        ?.getAttribute("points") ?? "",
    );
    for (const point of points) {
      expect(point.y).toBeGreaterThan(26.8);
    }
  });

  it("reserves the status palette: muted threshold within tolerance, destructive only on a genuine breach", () => {
    const { container, rerender } = render(
      <MetricSparklinePreview
        boundedRatio={{
          target: 3,
          bounds: { min: 0, max: 10 },
          withinTolerance: true,
        }}
        data={[2.5, 2.8, 2.2, 1.8]}
        form="bounded-ratio"
        label="Tỷ lệ hủy đơn"
        value="1,8%"
      />,
    );

    expect(
      container.querySelector("line[data-preview-target]"),
    ).toHaveAttribute("stroke", "var(--juli-muted-foreground)");
    expect(container.innerHTML).not.toContain("var(--juli-destructive)");
    expect(container.innerHTML).not.toContain("var(--juli-success)");

    rerender(
      <MetricSparklinePreview
        boundedRatio={{
          target: 3,
          bounds: { min: 0, max: 10 },
          withinTolerance: false,
        }}
        data={[2.5, 3.1, 3.6, 4.2]}
        form="bounded-ratio"
        label="Tỷ lệ hủy đơn"
        value="4,2%"
      />,
    );

    expect(
      container.querySelector("line[data-preview-target]"),
    ).toHaveAttribute("stroke", "var(--juli-destructive)");
    // The series itself never wears status color, even on breach.
    expect(
      container.querySelector("polyline[data-preview-line]"),
    ).toHaveAttribute("stroke", "var(--juli-chart-neutral)");
  });

  it("every form wears the neutral identity hue and exposes no trend prop", () => {
    for (const form of ["filled-line", "plain-line", "bars"] as const) {
      const { container, unmount } = render(
        <MetricSparklinePreview
          data={series}
          form={form}
          label="KPI"
          value="1"
        />,
      );

      const marks = container.querySelectorAll(
        "[data-preview-line], [data-preview-bar], [data-preview-fill]",
      );
      expect(marks.length).toBeGreaterThan(0);
      for (const mark of marks) {
        const paint =
          mark.getAttribute("stroke") === "none" ||
          mark.getAttribute("stroke") === null
            ? mark.getAttribute("fill")
            : mark.getAttribute("stroke");
        expect(paint).toBe("var(--juli-chart-neutral)");
      }
      unmount();
    }
  });

  it("keeps the text equivalent and an aria-hidden, non-focusable visual", () => {
    render(
      <MetricSparklinePreview
        data={series}
        delta="▲ 15%"
        form="filled-line"
        label="GMV TikTok"
        value="485 triệu"
      />,
    );

    expect(
      screen.getByText("GMV TikTok — 485 triệu — ▲ 15%"),
    ).toHaveClass("juli-sr-only");

    const visual = screen.getByTestId("metric-sparkline-preview");
    expect(visual).toHaveAttribute("aria-hidden", "true");
    expect(visual).toHaveAttribute("focusable", "false");
  });

  it("carries no hero chrome: no axes, gridlines, endpoint marker, or labels", () => {
    const { container } = render(
      <MetricSparklinePreview
        boundedRatio={{
          target: 3,
          bounds: { min: 0, max: 10 },
          withinTolerance: true,
        }}
        data={[2.5, 2.8, 2.2, 1.8]}
        form="bounded-ratio"
        label="Tỷ lệ hủy đơn"
        value="1,8%"
      />,
    );

    expect(container.querySelector("text")).toBeNull();
    expect(container.querySelector("[data-chart-endpoint-label]")).toBeNull();
    expect(container.querySelector("[data-chart-marker-endpoint]")).toBeNull();
    expect(container.querySelector(".recharts-cartesian-grid")).toBeNull();
    expect(container.querySelector(".recharts-xAxis")).toBeNull();
  });

  // #924 (DEMO-PREVIEW-SCALE): the regression this guards against is a
  // hardcoded pixel width (96) rendered inside a fluid, full-width container
  // (341px at 375px viewport) — the mark occupied 28% of its box, left
  // aligned. jsdom's getBoundingClientRect() returns an all-zero rect and
  // would pass trivially either way, so every assertion below reads authored
  // SVG attributes instead: the <svg>'s own `width`, and the mark's
  // rightmost/leftmost coordinates against the viewBox it fills.
  describe("fills its container's width, not a fixed pixel box (#924)", () => {
    it("renders the <svg> at width=\"100%\" with a non-stretch-preserving viewBox mapping", () => {
      const { container } = render(
        <MetricSparklinePreview
          data={series}
          form="plain-line"
          label="AOV"
          value="500.000 ₫"
        />,
      );

      const svg = container.querySelector("svg");
      // The defect: this used to be a literal `width="96"`, so the rendered
      // box was exactly 96px regardless of the container. Percentage sizing
      // is what makes the mark track whatever width the KPI card grid gives
      // it at any breakpoint.
      expect(svg).toHaveAttribute("width", "100%");
      expect(svg).toHaveAttribute("viewBox", "0 0 96 40");
      // Without this, the default "meet" aspect-ratio preservation would
      // letterbox the ~2.4:1 viewBox inside a much wider container instead of
      // stretching to fill it — reproducing the same left-aligned defect one
      // layer down.
      expect(svg).toHaveAttribute("preserveAspectRatio", "none");
    });

    it("a line mark's polyline spans the full viewBox width edge to edge", () => {
      const { container } = render(
        <MetricSparklinePreview
          data={series}
          form="plain-line"
          label="AOV"
          value="500.000 ₫"
        />,
      );

      const points = parsePoints(
        container
          .querySelector("polyline[data-preview-line]")
          ?.getAttribute("points") ?? "",
      );
      const xs = points.map((point) => point.x);
      // The viewBox is 96 wide (default internal coordinate space); a mark
      // that stopped short of it — e.g. by being drawn at a narrower fixed
      // width inside a wider viewBox — would leave blank space once that
      // viewBox is stretched to fill the container.
      expect(Math.min(...xs)).toBeCloseTo(0, 5);
      expect(Math.max(...xs)).toBeCloseTo(96, 5);
    });

    it("a bars mark's rightmost bar reaches the viewBox's right edge", () => {
      const counts = [6, 0, 10, 8] as const;
      const { container } = render(
        <MetricSparklinePreview
          data={counts}
          form="bars"
          label="LIVE hours"
          value="10 giờ"
        />,
      );

      const bars = [
        ...container.querySelectorAll("rect[data-preview-bar]"),
      ] as SVGRectElement[];
      const rightEdges = bars.map(
        (bar) => Number(bar.getAttribute("x")) + Number(bar.getAttribute("width")),
      );
      const leftEdges = bars.map((bar) => Number(bar.getAttribute("x")));

      // Bars are inset by half the inter-bar gap for visual balance, so the
      // edges sit just inside 0/96 rather than exactly on them — the
      // regression this guards is bars clustered in ~28% of the viewBox, not
      // sub-gap-width centering.
      expect(Math.min(...leftEdges)).toBeLessThan(2);
      expect(Math.max(...rightEdges)).toBeGreaterThan(94);
    });

    it("a bounded-ratio target line spans x1=0 to x2=width, matching the svg it renders inside", () => {
      const { container } = render(
        <MetricSparklinePreview
          boundedRatio={{
            target: 3,
            bounds: { min: 0, max: 10 },
            withinTolerance: true,
          }}
          data={[2.5, 2.8, 2.2, 1.8]}
          form="bounded-ratio"
          label="Tỷ lệ hủy đơn"
          value="1,8%"
        />,
      );

      const target = container.querySelector("line[data-preview-target]");
      expect(Number(target?.getAttribute("x1"))).toBeCloseTo(0, 5);
      expect(Number(target?.getAttribute("x2"))).toBeCloseTo(96, 5);
    });

    it("keeps the 1.5px stroke a literal visual-weight constant via non-scaling-stroke, independent of container width", () => {
      const { container } = render(
        <MetricSparklinePreview
          data={series}
          form="filled-line"
          label="GMV TikTok"
          value="485 triệu"
        />,
      );

      const line = container.querySelector("polyline[data-preview-line]");
      expect(line).toHaveAttribute("stroke-width", "1.5");
      expect(line).toHaveAttribute("vector-effect", "non-scaling-stroke");
    });
  });
});
