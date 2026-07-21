import { readFileSync } from "node:fs";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { usePathname, useRouter } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsDashboard } from "../components/analytics-dashboard";
import { DemoShell } from "../components/demo-shell";
import {
  DEFAULT_MUTABLE_MOCK_STATE,
  useDemoState,
} from "../components/demo-state";
import { MAIN_KPI_ORDER } from "../lib/analytics/main-kpis";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));

const push = vi.fn();
const replace = vi.fn();

function AnalyticsStateProbe() {
  const { mutableState } = useDemoState();

  return (
    <output data-testid="analytics-state">{JSON.stringify(mutableState)}</output>
  );
}

describe("Analytics dashboard", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue("/analytics/net-revenue");
    vi.mocked(useRouter).mockReturnValue({
      back: vi.fn(),
      forward: vi.fn(),
      prefetch: vi.fn(),
      push,
      refresh: vi.fn(),
      replace,
    });
    push.mockClear();
    replace.mockClear();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("AC1: renders one hero and five selector cards with Net Revenue at 30 days by default", () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="net-revenue" />
      </DemoShell>,
    );

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Doanh thu thuần",
    );
    expect(screen.getByRole("tab", { name: "30 ngày" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    const selectorCards = screen.getAllByTestId(/analytics-kpi-card-/);
    expect(selectorCards).toHaveLength(5);
    expect(MAIN_KPI_ORDER.filter((key) => key !== "net-revenue")).toHaveLength(
      5,
    );
  });

  it("AC2: shows documented mock values and charts for available KPIs", () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="net-revenue" />
      </DemoShell>,
    );

    expect(screen.getByText("485.000.000 ₫")).toHaveClass(
      "analytics-hero__value",
    );
    expect(screen.getByText("▲ 15%")).toBeInTheDocument();
    expect(
      document.querySelector('[data-testid="trend-line-chart-visual"]'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Doanh thu thuần — .* — ▲ 15%/),
    ).toHaveClass("juli-sr-only");
  });

  it("AC3: keeps SPS, ROAS, and CSAT visible, unavailable, and non-selectable without fake values", () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="net-revenue" />
      </DemoShell>,
    );

    for (const key of ["sps", "roas", "csat"] as const) {
      const card = screen.getByTestId(`analytics-kpi-card-${key}`);

      expect(card).toHaveClass("analytics-kpi-card--unavailable");
      expect(within(card).getByText("Chưa khả dụng")).toBeInTheDocument();
      expect(
        within(card).getByTestId("analytics-unavailable-chart"),
      ).toBeInTheDocument();
      expect(within(card).queryByText(/^0/)).not.toBeInTheDocument();
    }
  });

  it("AC4: swaps hero and card selection while updating browser history", async () => {
    const user = userEvent.setup();

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="net-revenue" />
        <AnalyticsStateProbe />
      </DemoShell>,
    );

    await user.click(
      screen.getByTestId("analytics-kpi-card-inventory-turnover"),
    );

    expect(push).toHaveBeenCalledWith("/analytics/inventory-turnover");
    expect(screen.getByTestId("analytics-state")).toHaveTextContent(
      "inventory-turnover",
    );
    expect(
      screen.getByTestId("analytics-kpi-card-net-revenue"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("analytics-kpi-card-inventory-turnover"),
    ).not.toBeInTheDocument();
  });

  it("AC5: updates hero and previews when range changes and keeps comparison hero-only", async () => {
    const user = userEvent.setup();

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="net-revenue" />
      </DemoShell>,
    );

    await user.click(screen.getByRole("tab", { name: "7 ngày" }));

    expect(screen.getByText("▲ 8%")).toBeInTheDocument();

    const inventoryCard = screen.getByTestId(
      "analytics-kpi-card-inventory-turnover",
    );
    expect(
      within(inventoryCard).getByText("4,2x", { selector: ".analytics-kpi-card__value" }),
    ).toBeInTheDocument();

    await user.click(screen.getByLabelText("So sánh kỳ trước"));
    expect(
      screen.getByText("Đường liền: kỳ hiện tại · Đường nét đứt: kỳ trước"),
    ).toBeInTheDocument();
    expect(
      within(inventoryCard).queryByText("Đường liền: kỳ hiện tại"),
    ).not.toBeInTheDocument();
  });

  it("AC6: exposes provenance, freshness, decision links, and invalid deep links", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="net-revenue" />
      </DemoShell>,
    );

    expect(screen.getByText(/Nguồn dữ liệu:/)).toBeInTheDocument();
    expect(screen.getByText(/Cập nhật lần cuối:/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Xem đề xuất tối ưu sản phẩm" }),
    ).toHaveAttribute("href", "/decisions?highlight=optimize_product_2");

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="unknown-metric" />
      </DemoShell>,
    );

    expect(screen.getByRole("heading", { name: "KPI không tìm thấy" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Xem Doanh thu thuần" }),
    ).toHaveAttribute("href", "/analytics/net-revenue");
  });

  it("AC6: preserves selection on error and supports retry plus partial data", async () => {
    const user = userEvent.setup();

    const { rerender } = render(
      <DemoShell>
        <AnalyticsDashboard initialLoadState="error" metricKey="net-revenue" />
      </DemoShell>,
    );

    expect(
      screen.getByText(/Chưa thể tải dữ liệu KPI/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(screen.getByText("485.000.000 ₫")).toHaveClass(
      "analytics-hero__value",
    );

    rerender(
      <DemoShell>
        <AnalyticsDashboard initialLoadState="partial" metricKey="net-revenue" key="partial" />
      </DemoShell>,
    );

    expect(
      screen.getByText(/Một phần dữ liệu nguồn chưa đầy đủ/),
    ).toBeInTheDocument();
  });

  it("AC6: shows stable hero and five-card loading skeletons", () => {
    render(
      <DemoShell>
        <AnalyticsDashboard initialLoadState="loading" metricKey="net-revenue" />
      </DemoShell>,
    );

    expect(screen.getByLabelText("Đang tải KPI chính")).toBeInTheDocument();
    expect(document.querySelectorAll(".analytics-skeleton--card")).toHaveLength(5);
  });

  it("AC7: Manual Refresh restores Net Revenue, 30 days, and comparison off", async () => {
    const user = userEvent.setup();

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="inventory-turnover" />
        <AnalyticsStateProbe />
      </DemoShell>,
    );

    await user.click(screen.getByRole("tab", { name: "90 ngày" }));
    await user.click(screen.getByLabelText("So sánh kỳ trước"));
    await user.click(screen.getByRole("button", { name: "Làm mới Demo" }));

    expect(screen.getByTestId("analytics-state")).toHaveTextContent(
      JSON.stringify(DEFAULT_MUTABLE_MOCK_STATE),
    );
    expect(replace).toHaveBeenCalledWith("/decisions");
  });

  it("AC8: includes responsive layout hooks and reduced-motion safeguards in styles", () => {
    const css = readFileSync("src/app/globals.css", "utf8");

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="net-revenue" />
      </DemoShell>,
    );

    expect(css).toContain(".analytics-dashboard");
    expect(css).toContain(".analytics-kpi-grid");
    expect(css).toContain("@media (max-width: 35rem)");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(
      screen.getByText(/Doanh thu thuần — .* — ▲ 15%/),
    ).toHaveClass("juli-sr-only");
  });
});
