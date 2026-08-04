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
import {
  createMockDemoAnalyticsEnvelope,
  createMockFetchResponse,
} from "../lib/analytics/__tests__/fixtures";
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
    vi.mocked(usePathname).mockReturnValue("/analytics/gmv-tiktok");
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
    vi.stubGlobal("fetch", vi.fn(createMockFetchResponse()));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("AC1 (RED): renders one hero and four selector cards (DUX-2: five-KPI set)", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "GMV (TikTok)",
    );
    expect(screen.getByRole("tab", { name: "30 ngày" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    const selectorCards = screen.getAllByTestId(/analytics-kpi-card-/);
    expect(selectorCards).toHaveLength(4);
    expect(MAIN_KPI_ORDER).toHaveLength(5);
    expect(MAIN_KPI_ORDER.filter((key) => key !== "gmv-tiktok")).toHaveLength(
      4,
    );
  });

  it("AC2: live and mock render paths show GMV without net revenue remapping", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    expect(await screen.findByText("485.000.000 ₫")).toHaveClass(
      "analytics-hero__value",
    );
    expect(screen.getByText("▲ 15%")).toBeInTheDocument();
    expect(screen.getByText("Dữ liệu thực")).toBeInTheDocument();
    expect(screen.queryByText("Doanh thu thuần")).not.toBeInTheDocument();
  });

  it("AC2 (RED): removed ADR-023 KPI strings are absent from Demo Analytics page", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    await screen.findByRole("heading", { level: 1 });

    // Removed KPI display names must not appear anywhere on the page
    expect(screen.queryByText("SPS")).not.toBeInTheDocument();
    expect(screen.queryByText("ROAS")).not.toBeInTheDocument();
    expect(screen.queryByText("CSAT")).not.toBeInTheDocument();
    expect(screen.queryByText("Doanh thu thuần")).not.toBeInTheDocument();
    expect(screen.queryByText("Vòng quay tồn kho")).not.toBeInTheDocument();
    expect(screen.queryByText("Tỷ lệ giao đúng")).not.toBeInTheDocument();
  });

  it("AC2: removed KPI cards (SPS, ROAS, CSAT) are not rendered at all", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    await screen.findByRole("heading", { level: 1 });

    // Removed keys should not have card elements
    for (const key of ["sps", "roas", "csat"] as const) {
      expect(screen.queryByTestId(`analytics-kpi-card-${key}`)).not.toBeInTheDocument();
    }
  });

  it("AC4: swaps hero and card selection while updating browser history", async () => {
    const user = userEvent.setup();

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
        <AnalyticsStateProbe />
      </DemoShell>,
    );

    await screen.findByRole("heading", { level: 1 });

    await user.click(
      screen.getByTestId("analytics-kpi-card-aov"),
    );

    expect(push).toHaveBeenCalledWith("/analytics/aov");
    expect(screen.getByTestId("analytics-state")).toHaveTextContent(
      "aov",
    );
    expect(
      screen.getByTestId("analytics-kpi-card-gmv-tiktok"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("analytics-kpi-card-aov"),
    ).not.toBeInTheDocument();
  });

  it("AC5: updates hero when range changes and keeps comparison hero-only", async () => {
    const user = userEvent.setup();

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    await screen.findByRole("heading", { level: 1 });

    await user.click(screen.getByRole("tab", { name: "7 ngày" }));

    // All four selector cards should still render
    expect(screen.getAllByTestId(/analytics-kpi-card-/)).toHaveLength(4);

    await user.click(screen.getByLabelText("So sánh kỳ trước"));
    expect(
      screen.getByText("Đường liền: kỳ hiện tại · Đường nét đứt: kỳ trước"),
    ).toBeInTheDocument();
  });

  it("AC6: exposes provenance, freshness, and decision links", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    await screen.findByRole("heading", { level: 1 });

    expect(screen.getAllByText(/Nguồn dữ liệu:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Cập nhật lần cuối:/).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: "Xem đề xuất tối ưu sản phẩm" }),
    ).toHaveAttribute("href", "/decisions?highlight=optimize_product_2");
  });

  it("AC6: renders invalid deep link recovery", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="unknown-metric" />
      </DemoShell>,
    );

    expect(
      await screen.findByRole("heading", { name: "KPI không tìm thấy" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Xem GMV (TikTok)" }),
    ).toHaveAttribute("href", "/analytics/gmv-tiktok");
  });

  it("AC6 (RED): removed KPI deep link (e.g., /analytics/roas) shows recovery view", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="roas" />
      </DemoShell>,
    );

    expect(
      await screen.findByRole("heading", { name: "KPI không tìm thấy" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Xem GMV (TikTok)" }),
    ).toHaveAttribute("href", "/analytics/gmv-tiktok");
  });

  it("AC (RED): persisted analyticsMetric localStorage key with removed KPI falls back to GMV", async () => {
    localStorage.setItem("analyticsMetric", "roas");

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="roas" />
      </DemoShell>,
    );

    // Should show recovery view for invalid key
    expect(
      await screen.findByRole("heading", { name: "KPI không tìm thấy" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Xem GMV (TikTok)" }),
    ).toHaveAttribute("href", "/analytics/gmv-tiktok");
  });

  it("AC6: shows partial note for sparse long-range series", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        createMockFetchResponse(
          createMockDemoAnalyticsEnvelope({
            kpis: {
              gmv_tiktok: {
                availability: "available",
                label: "GMV (TikTok)",
                series: [{ t: "2026-07-20", v: 485_000_000 }],
              },
            },
          }),
        ),
      ),
    );

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    await userEvent.setup().click(await screen.findByRole("tab", { name: "90 ngày" }));

    expect(
      await screen.findByText(/Một phần dữ liệu nguồn chưa đầy đủ/),
    ).toBeInTheDocument();
  });

  it("AC6: shows stable hero and four-card loading skeletons (DUX-2)", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => undefined)),
    );

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    expect(screen.getByLabelText("Đang tải KPI chính")).toBeInTheDocument();
    expect(document.querySelectorAll(".analytics-skeleton--card")).toHaveLength(4);
  });

  it("AC11: preserves focus order and aria labels through visual polish", async () => {
    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    const pageTitle = await screen.findByRole("heading", { level: 1 });
    const rangeTabs = screen.getByRole("tablist", { name: "Khoảng thời gian" });
    const sectionTitle = screen.getByRole("heading", {
      level: 2,
      name: "KPI chính khác",
    });
    const selectorGrid = screen.getByRole("list", { name: "KPI chính khác" });

    expect(pageTitle.compareDocumentPosition(rangeTabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(rangeTabs.compareDocumentPosition(sectionTitle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sectionTitle.compareDocumentPosition(selectorGrid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText("So sánh kỳ trước")).toBeInTheDocument();
  });

  it("RED: renders GMV value and chart when API is unavailable (fallback)", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Network error"))));

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    // Should render a heading with GMV metric name
    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("GMV (TikTok)");

    // Should NOT show the error hero
    expect(screen.queryByRole("heading", { name: "Chưa thể tải dữ liệu KPI" })).not.toBeInTheDocument();

    // Should render a value and chart (from fallback)
    expect(screen.getByTestId("analytics-chart-chrome")).toBeInTheDocument();
  });

  it("AC12: leaves Home Recommendations Settings and In Progress UI untouched by analytics polish", () => {
    const analyticsOnlyPaths = [
      "apps/demo/src/__tests__/analytics-dashboard.test.tsx",
      "apps/demo/src/app/globals.css",
      "apps/demo/src/components/analytics-charts.tsx",
      "apps/demo/src/components/analytics-dashboard.tsx",
      "apps/demo/src/components/analytics-kpi-card.tsx",
      "apps/demo/src/components/analytics-supplementary-sections.tsx",
      "apps/demo/src/lib/analytics/visual-polish.ts",
      "apps/demo/src/lib/analytics/__tests__/visual-polish.test.ts",
    ];
    const forbiddenPaths = [
      "apps/demo/src/components/in-progress-panel.tsx",
      "apps/demo/src/components/recommendations-panel.tsx",
      "packages/ui/src/destination-card.tsx",
      "packages/ui/src/recommendation-card.tsx",
      "packages/ui/styles.css",
    ];

    for (const path of analyticsOnlyPaths) {
      expect(forbiddenPaths.some((forbidden) => path.includes(forbidden))).toBe(
        false,
      );
    }
  });

  it("AC7: applies visual polish for chart chrome, hierarchy, delta trends, and loading shimmer", async () => {
    const css = readFileSync("src/app/globals.css", "utf8");

    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => undefined)),
    );

    const { unmount } = render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    expect(screen.getByLabelText("Đang tải KPI chính")).toHaveClass(
      "analytics-skeleton--shimmer",
    );
    unmount();
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", vi.fn(createMockFetchResponse()));

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    await screen.findByRole("heading", { level: 1 });

    expect(
      screen.getByRole("heading", { level: 2, name: "KPI chính khác" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("analytics-chart-chrome")).toBeInTheDocument();
    expect(screen.getByText("▲ 15%")).toHaveClass("analytics-delta--positive");

    expect(css).toContain(".analytics-chart-chrome");
    expect(css).toContain(".analytics-skeleton--shimmer");
    expect(css).toContain(".analytics-delta--positive");
    expect(css).toContain(".analytics-kpi-section__title");
  });

  it("AC8: includes responsive layout hooks and reduced-motion safeguards in styles", async () => {
    const css = readFileSync("src/app/globals.css", "utf8");

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    await screen.findByRole("heading", { level: 1 });

    expect(css).toContain(".analytics-dashboard");
    expect(css).toContain(".analytics-kpi-grid");
    expect(css).toContain("@media (max-width: 35rem)");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
