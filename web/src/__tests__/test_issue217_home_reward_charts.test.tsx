/**
 * Issue #217 — Home Reward charts + CTAs to Decisions (P1.8-10)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TodaysReportPanel } from "@/components/home/todays-report";
import { DecisionPreviewCard } from "@/components/workflows/operations/DecisionPreviewCard";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { toDecision, isValidatedWorkflowId } from "@/lib/decisions";
import { loadOperationalModelForPersona } from "@/lib/mock-data/operations";
import { ModeProvider } from "@/lib/mode-context";
import {
  buildDecisionsHighlightLink,
  getJourneyLink,
} from "@/lib/operations/journey-loop";
import {
  SPARKLINE_POINT_COUNT,
  buildDomainReportSummary,
  deriveSparklineSeries,
} from "@/lib/operations/todays-report";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
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

function renderSellerHomeWithPersona(personaId: "growth" | "leakage" = "growth") {
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

describe("Issue #217: Home Reward charts + CTAs", () => {
  it("derives deterministic 7-point sparkline series from model inputs", () => {
    const model = loadOperationalModelForPersona("growth");
    const summary = buildDomainReportSummary("revenue_growth", model);
    const revenueMetric = summary.metrics.find((metric) => metric.metricKey === "revenue_7d");

    expect(revenueMetric?.series).toHaveLength(SPARKLINE_POINT_COUNT);
    expect(deriveSparklineSeries(100, 80, "seed-a")).toEqual(
      deriveSparklineSeries(100, 80, "seed-a"),
    );
    expect(deriveSparklineSeries(100, 80, "seed-a")).not.toEqual(
      deriveSparklineSeries(100, 80, "seed-b"),
    );
  });

  it("renders revenue and units sparklines with delta labels on growth Tăng trưởng tab", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-card-revenue_growth")).toBeInTheDocument();
    });

    const revenueChart = screen.getByTestId(
      "report-metric-chart-revenue_growth-revenue_7d",
    );
    const unitsChart = screen.getByTestId(
      "report-metric-chart-revenue_growth-units_sold_7d",
    );

    expect(revenueChart).toBeInTheDocument();
    expect(unitsChart).toBeInTheDocument();
    expect(within(revenueChart).getByTestId("report-metric-delta")).toBeVisible();
    expect(within(unitsChart).getByTestId("report-metric-delta")).toBeVisible();
    expect(revenueChart.querySelector("polyline")).toBeInTheDocument();
    expect(unitsChart.querySelector("polyline")).toBeInTheDocument();
  });

  it("wires chart CTAs through the journey registry deep links", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-cta-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    const revenueCta = screen.getByTestId("report-metric-cta-revenue_growth-revenue_7d");
    const unitsCta = screen.getByTestId("report-metric-cta-revenue_growth-units_sold_7d");

    expect(revenueCta).toHaveAttribute(
      "href",
      buildDecisionsHighlightLink("product_scaling"),
    );
    expect(unitsCta).toHaveAttribute(
      "href",
      buildDecisionsHighlightLink("product_scaling"),
    );
    expect(revenueCta).toHaveTextContent("Xem đề xuất liên quan");
  });

  it("makes opportunity preview cards fully tappable decision deep links", async () => {
    const pipeline = runOperationsPipeline("growth");
    const topWorkflow = pipeline.workflowRecommendations.recommended_workflows[0];
    const decision = toDecision(topWorkflow);

    render(<DecisionPreviewCard decision={decision} />);

    const link = screen.getByTestId(`decision-preview-link-${decision.workflow_id}`);
    expect(link).toHaveAttribute(
      "href",
      buildDecisionsHighlightLink(decision.workflow_id),
    );
    expect(getJourneyLink(decision.workflow_id)).not.toBeNull();
  });

  it("renders preview cards on Home as tappable deep links", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("decision-preview-list")).toBeInTheDocument();
    });

    const links = screen.getAllByTestId(/^decision-preview-link-/);
    expect(links.length).toBeGreaterThan(0);

    for (const link of links) {
      const workflowId = link
        .getAttribute("data-testid")
        ?.replace("decision-preview-link-", "");
      expect(workflowId).toBeTruthy();
      expect(isValidatedWorkflowId(workflowId!)).toBe(true);
      if (isValidatedWorkflowId(workflowId!)) {
        expect(link).toHaveAttribute("href", buildDecisionsHighlightLink(workflowId));
      }
    }
  });

  it("exposes report metric chart and CTA test ids without chart library dependencies", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("report-metric-cta-revenue_growth-revenue_7d"),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId(/^decision-preview-link-/).length).toBeGreaterThan(0);

    const pkg = (await import("../../package.json")).default as {
      dependencies?: Record<string, string>;
    };
    expect(pkg.dependencies?.recharts).toBeUndefined();
    expect(pkg.dependencies?.["chart.js"]).toBeUndefined();
  });

  it("disables chart entry animation when prefers-reduced-motion is reduce", async () => {
    mockMatchMedia(true);

    render(
      <TodaysReportPanel
        model={loadOperationalModelForPersona("growth")}
        profile="MID_LARGE_SHOP"
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    const chart = screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d");
    expect(chart).toHaveAttribute("data-animate", "false");
    expect(chart).not.toHaveClass("report-metric-chart-animate");
  });
});
