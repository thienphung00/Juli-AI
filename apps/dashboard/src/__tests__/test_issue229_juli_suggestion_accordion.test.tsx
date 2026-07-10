/**
 * Issue #229 — Metric tiles: Juli suggestion two-step accordion + keyboard
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TodaysReportPanel } from "@/components/home/todays-report";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  buildDecisionsHighlightLink,
  resolveJourneyLinkForMetric,
} from "@/lib/operations/journey-loop";
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

describe("Issue #229: Juli suggestion two-step accordion", () => {
  it("shows Gợi ý từ Juli with info styling when revenue tile is expanded", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d")).toBeInTheDocument();
    });

    const expandToggle = screen.getByTestId(
      "report-metric-suggestion-expand-revenue_growth-revenue_7d",
    );
    expect(expandToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("report-metric-cta-revenue_growth-revenue_7d")).not.toBeInTheDocument();

    await user.click(expandToggle);

    expect(expandToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Gợi ý từ Juli")).toBeInTheDocument();

    const suggestionPanel = screen.getByTestId(
      "report-metric-suggestion-panel-revenue_growth-revenue_7d",
    );
    const suggestionLabel = within(suggestionPanel).getByText("Gợi ý từ Juli").parentElement;
    expect(suggestionLabel).toHaveStyle({ color: "var(--info)" });

    const journeyLink = resolveJourneyLinkForMetric("revenue_growth", "revenue_7d");
    expect(journeyLink?.reasonTemplate).toBeTruthy();
    expect(suggestionPanel.textContent).toContain(
      journeyLink!.reasonTemplate.replace(/\*\*/g, ""),
    );
  });

  it("integration: expanded revenue tile CTA href matches buildDecisionsHighlightLink", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    await user.click(
      screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
    );

    const cta = screen.getByTestId("report-metric-cta-revenue_growth-revenue_7d");
    expect(cta).toHaveAttribute(
      "href",
      buildDecisionsHighlightLink("budget_optimization"),
    );
  });

  it("keyboard: Enter toggles expand and Tab reaches Decisions CTA", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    const expandToggle = screen.getByTestId(
      "report-metric-suggestion-expand-revenue_growth-revenue_7d",
    );
    expandToggle.focus();
    await user.keyboard("{Enter}");

    expect(expandToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("report-metric-cta-revenue_growth-revenue_7d")).toBeInTheDocument();

    await user.tab();
    expect(screen.getByTestId("report-metric-cta-revenue_growth-revenue_7d")).toHaveFocus();
  });

  it("keeps estimated bar as secondary fallback link on growth revenue tile", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-estimated-revenue_growth-revenue_7d-estimated"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("report-metric-estimated-revenue_growth-revenue_7d-estimated"),
    ).toHaveAttribute("href", buildDecisionsHighlightLink("budget_optimization"));
  });

  it("renders accordion on metrics with journey links in TodaysReportPanel", async () => {
    const user = userEvent.setup();
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
        screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    await user.click(
      screen.getByTestId("report-metric-suggestion-expand-revenue_growth-roas"),
    );
    expect(
      screen.getByTestId("report-metric-suggestion-panel-revenue_growth-roas"),
    ).toBeInTheDocument();
  });

  it("uses info token styling instead of purple AI gradients on Juli suggestion panel", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    await user.click(
      screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
    );

    const suggestionPanel = screen.getByTestId(
      "report-metric-suggestion-panel-revenue_growth-revenue_7d",
    );
    expect(suggestionPanel.className).not.toMatch(/purple|violet|ai-gradient/i);
    expect(suggestionPanel).toHaveStyle({
      background: "color-mix(in srgb, var(--info) 6%, transparent)",
    });
  });
});
