/**
 * Issue #228 — Tăng trưởng tab: Recharts sparklines + Profit/margin tile
 */
import { render, screen, waitFor } from "@testing-library/react";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { TodaysReportPanel } from "@/components/home/todays-report";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import {
  SPARKLINE_POINT_COUNT,
  buildDomainReportSummary,
  deriveSparklineSeries,
} from "@/lib/operations/todays-report";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

jest.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { id: "user-1", phone: "+84912345678" },
    token: "jwt-token",
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/",
}));

function mockMatchMedia(reducedMotion: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: jest.fn().mockImplementation((query: string) => ({
      matches: query.includes("prefers-reduced-motion") ? reducedMotion : false,
      media: query,
      onchange: null,
      addListener: jest.fn(),
      removeListener: jest.fn(),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    })),
  });
}

function renderSellerHomeWithPersona(personaId: "growth" | "leakage" | "new" = "growth") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <SellerHomeShell />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
  mockMatchMedia(false);
});

describe("Issue #228: growth sparklines + profit tile", () => {
  it("builds deterministic 7-point sparkline series from model inputs", () => {
    const series = deriveSparklineSeries(100, 80, "shop:revenue_growth:revenue_7d");
    expect(series).toHaveLength(SPARKLINE_POINT_COUNT);
    expect(series[0]).toBeGreaterThanOrEqual(0);
    expect(series[series.length - 1]).toBe(100);

    const repeat = deriveSparklineSeries(100, 80, "shop:revenue_growth:revenue_7d");
    expect(repeat).toEqual(series);
  });

  it("includes distinct Doanh thu and Lợi nhuận / biên tiles in growth summary", () => {
    const pipeline = runOperationsPipeline("growth");
    const summary = buildDomainReportSummary("revenue_growth", pipeline.unifiedModel);
    const keys = summary.metrics.map((metric) => metric.metricKey);

    expect(keys).toContain("revenue_7d");
    expect(keys).toContain("profit_margin");
    expect(keys.indexOf("revenue_7d")).toBeLessThan(keys.indexOf("profit_margin"));

    const profitTile = summary.metrics.find((metric) => metric.metricKey === "profit_margin");
    expect(profitTile?.label).toBe("Lợi nhuận / biên");
    expect(profitTile?.series).toHaveLength(SPARKLINE_POINT_COUNT);
  });

  it("integration: growth Tăng trưởng tab renders profit tile and Recharts sparklines", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-card-revenue_growth")).toBeInTheDocument();
    });

    expect(screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d")).toBeInTheDocument();
    expect(screen.getByTestId("report-metric-chart-revenue_growth-profit_margin")).toBeInTheDocument();
    expect(
      screen.getByTestId("report-metric-sparkline-revenue_growth-revenue_7d"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("report-metric-sparkline-revenue_growth-profit_margin"),
    ).toBeInTheDocument();

    const revenueSparkline = screen.getByTestId(
      "report-metric-sparkline-revenue_growth-revenue_7d",
    );
    expect(revenueSparkline.querySelector(".recharts-wrapper")).toBeInTheDocument();
  });

  it("disables sparkline entry animation when prefers-reduced-motion is reduce", async () => {
    mockMatchMedia(true);
    const pipeline = runOperationsPipeline("growth");

    render(
      <TodaysReportPanel
        model={pipeline.unifiedModel}
        profile={pipeline.shopProfile}
        recommendations={pipeline.workflowRecommendations.recommended_workflows}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-sparkline-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    const sparkline = screen.getByTestId("report-metric-sparkline-revenue_growth-revenue_7d");
    expect(sparkline).toHaveAttribute("data-animate", "false");
  });
});
