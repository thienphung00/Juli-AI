import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  CHART_SERIES_COLORS,
  ChartExpandableTile,
  ChartTextEquivalent,
  MetricSparkline,
  TrendAreaChart,
  TrendLineChart,
} from "../chart";
import { loadUiStyles } from "./test-utils";

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
    expect(CHART_SERIES_COLORS.neutral).toBe("var(--juli-primary)");
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
});
