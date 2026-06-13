/**
 * Issue #217 — Home Real/Estimated visualizations + decision linking (P1.8-10 reopen)
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
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import { REPORT_DOMAIN_IDS } from "@/lib/operations/todays-report";
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

describe("Issue #217: Home Real/Estimated visualizations", () => {
  it("renders exactly three Daily Report domain tabs", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    expect(REPORT_DOMAIN_IDS).toHaveLength(3);
    for (const domainId of REPORT_DOMAIN_IDS) {
      expect(screen.getByTestId(`todays-report-tab-${domainId}`)).toBeInTheDocument();
    }
    expect(screen.queryByTestId("todays-report-tab-revenue_protection")).not.toBeInTheDocument();
    expect(screen.queryByTestId("todays-report-tab-advertising")).not.toBeInTheDocument();
  });

  it("renders Shop Health SPS/AHR as two-tone bars with estimated affordance", async () => {
    renderSellerHomeWithPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-sps-estimated")).toBeInTheDocument();
    });

    expect(screen.getByTestId("shop-health-ahr-estimated")).toBeInTheDocument();
    expect(screen.getByTestId("shop-health-sps-real")).toBeInTheDocument();
    expect(screen.getByTestId("shop-health-sps-tick-3_5")).toBeInTheDocument();
    expect(screen.getByTestId("shop-health-sps-tick-4_5")).toBeInTheDocument();

    const spsEstimated = screen.getByTestId("shop-health-sps-estimated");
    expect(spsEstimated).toHaveAttribute("href", buildDecisionsHighlightLink("npl"));
    expect(spsEstimated.getAttribute("title")).toMatch(/nếu phê duyệt/);
    expect(spsEstimated.getAttribute("title")).not.toMatch(/if approved/i);
    expect(screen.queryByTestId("report-metric-cta-revenue_growth-revenue_7d")).not.toBeInTheDocument();
  });

  it("renders growth metrics as Real/Estimated bars linked to budget_optimization", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-card-revenue_growth")).toBeInTheDocument();
    });

    const revenueEstimated = screen.getByTestId(
      "report-metric-estimated-revenue_growth-revenue_7d-estimated",
    );
    const unitsEstimated = screen.getByTestId(
      "report-metric-estimated-revenue_growth-units_sold_7d-estimated",
    );
    const roasEstimated = screen.getByTestId(
      "report-metric-estimated-revenue_growth-roas-estimated",
    );

    expect(revenueEstimated).toHaveAttribute(
      "href",
      buildDecisionsHighlightLink("budget_optimization"),
    );
    expect(unitsEstimated).toHaveAttribute(
      "href",
      buildDecisionsHighlightLink("budget_optimization"),
    );
    expect(roasEstimated).toHaveAttribute(
      "href",
      buildDecisionsHighlightLink("budget_optimization"),
    );
    expect(screen.queryByText("Xem đề xuất liên quan")).not.toBeInTheDocument();
  });

  it("links inventory and refund metrics to distinct workflow actions", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("leakage");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("todays-report-tab-inventory_refunds"));

    expect(
      screen.getByTestId("report-metric-estimated-inventory_refunds-low_stock_rate-estimated"),
    ).toHaveAttribute("href", buildDecisionsHighlightLink("stockout_prevention"));
    expect(
      screen.getByTestId("report-metric-estimated-inventory_refunds-refund_rate_7d-estimated"),
    ).toHaveAttribute("href", buildDecisionsHighlightLink("refund_spike_detection"));
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

  it("renders Recharts sparklines on growth revenue and profit tiles", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-sparkline-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("report-metric-sparkline-revenue_growth-profit_margin"),
    ).toBeInTheDocument();

    const pkg = (await import("../../package.json")).default as {
      dependencies?: Record<string, string>;
    };
    expect(pkg.dependencies?.recharts).toBeDefined();
  });

  it("disables chart entry animation when prefers-reduced-motion is reduce", async () => {
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
        screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    const chart = screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d");
    expect(chart).toHaveAttribute("data-animate", "false");
    expect(chart).not.toHaveClass("report-metric-chart-animate");
  });
});
