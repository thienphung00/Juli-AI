import { describe, expect, it } from "vitest";

import {
  ChartExpandableTile,
  ChartTextEquivalent,
  LoadingIndicator,
  LoadingSkeleton,
  LoadingSpinner,
  MetricSparkline,
  PageHeader,
  PrimaryNavigation,
  Toast,
  ToastViewport,
  TrendAreaChart,
  TrendLineChart,
  isNavTabActive,
} from "@juli/ui";

describe("Demo import boundary for @juli/ui #414 compositions", () => {
  it("imports feedback, navigation, and chart exports from the shared package", () => {
    expect(Toast).toBeTypeOf("function");
    expect(ToastViewport).toBeTypeOf("function");
    expect(LoadingSpinner).toBeTypeOf("function");
    expect(LoadingSkeleton).toBeTypeOf("function");
    expect(LoadingIndicator).toBeTypeOf("function");
    expect(PrimaryNavigation).toBeTypeOf("function");
    expect(isNavTabActive).toBeTypeOf("function");
    expect(PageHeader).toBeTypeOf("function");
    expect(MetricSparkline).toBeTypeOf("function");
    expect(TrendAreaChart).toBeTypeOf("function");
    expect(TrendLineChart).toBeTypeOf("function");
    expect(ChartExpandableTile).toBeTypeOf("function");
    expect(ChartTextEquivalent).toBeTypeOf("function");
  });
});
