/**
 * Issue #221 — RRAA loop E2E + chart-first exit gate (P1.8-10)
 *
 * Full growth-persona loop: Home Juli suggestion → Decisions highlight → Home return.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionsPage } from "@/components/DecisionsPage";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  buildDecisionsHighlightLink,
  buildHomeHighlightLink,
  resolveHomeHighlight,
} from "@/lib/operations/journey-loop";
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

const mockSearchParams = new URLSearchParams();
let mockPathname = "/";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => mockPathname,
  useSearchParams: () => mockSearchParams,
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

function renderSellerHome(personaId: "growth" = "growth") {
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

function renderDecisions(personaId: "growth" = "growth") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <DecisionsPage />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

function assertChartFirstHomeGate() {
  expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
  expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();
  expect(screen.queryByText("Reward")).not.toBeInTheDocument();
  expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
  expect(screen.queryByTestId(/^approval-approve-/)).not.toBeInTheDocument();
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
  mockMatchMedia(false);
  mockPathname = "/";
  mockSearchParams.forEach((_, key) => {
    mockSearchParams.delete(key);
  });
  Element.prototype.scrollIntoView = jest.fn();
});

describe("Issue #221: chart-first Home gate (growth persona)", () => {
  it("has no preview, Tiến độ, Reward labels, or approve CTAs on /", async () => {
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
    });

    assertChartFirstHomeGate();
  });
});

describe("Issue #221: RRAA loop E2E — growth persona", () => {
  it("completes Home → Decisions → Home via Juli suggestion CTA and Xem trên Trang chủ", async () => {
    const user = userEvent.setup();
    const workflowId = "budget_optimization";

    mockPathname = "/";
    renderSellerHome("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    assertChartFirstHomeGate();

    await user.click(
      screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
    );

    const decisionsCta = screen.getByTestId("report-metric-cta-revenue_growth-revenue_7d");
    expect(decisionsCta).toHaveAttribute("href", buildDecisionsHighlightLink(workflowId));

    cleanup();
    mockPathname = "/decisions";
    mockSearchParams.set("highlight", workflowId);
    renderDecisions("growth");

    await waitFor(() => {
      const card = document.querySelector(`[data-workflow-id="${workflowId}"]`);
      expect(card).toHaveAttribute("data-highlighted", "true");
    });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();

    const homeLink = screen.getByTestId(`clarity-card-home-link-${workflowId}`);
    expect(homeLink).toHaveTextContent("Xem trên Trang chủ");
    const homeHref = homeLink.getAttribute("href");
    expect(homeHref).toBe(
      buildHomeHighlightLink(resolveHomeHighlight(workflowId)!),
    );

    const homeHighlight = new URL(homeHref!, "http://localhost").searchParams.get("highlight");
    expect(homeHighlight).toBe("revenue_growth:roas");

    cleanup();
    mockPathname = "/";
    mockSearchParams.delete("highlight");
    mockSearchParams.set("highlight", homeHighlight!);
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel-revenue_growth")).toBeInTheDocument();
      expect(screen.getByTestId("report-metric-chart-revenue_growth-roas")).toHaveAttribute(
        "data-highlighted",
        "true",
      );
    });

    expect(screen.getByTestId("todays-report-tab-revenue_growth")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    assertChartFirstHomeGate();
  });

  it("supports estimated-bar fallback as second tap into the same Decisions highlight", async () => {
    const workflowId = "budget_optimization";

    renderSellerHome("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-estimated-revenue_growth-roas-estimated"),
      ).toBeInTheDocument();
    });

    const estimatedLink = screen.getByTestId(
      "report-metric-estimated-revenue_growth-roas-estimated",
    );
    expect(estimatedLink).toHaveAttribute("href", buildDecisionsHighlightLink(workflowId));

    cleanup();
    mockPathname = "/decisions";
    mockSearchParams.set("highlight", workflowId);
    renderDecisions("growth");

    await waitFor(() => {
      expect(screen.getByTestId(`clarity-card-home-link-${workflowId}`)).toBeInTheDocument();
    });

    const card = document.querySelector(`[data-workflow-id="${workflowId}"]`);
    expect(card).toHaveAttribute("data-highlighted", "true");
  });
});
