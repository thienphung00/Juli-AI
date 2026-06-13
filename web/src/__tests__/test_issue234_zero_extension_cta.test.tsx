/**
 * Issue #234 — Inventory metrics: CTA state when estimated bar has no extension
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import {
  buildDecisionsHighlightLink,
  resolveJourneyLinkForMetric,
} from "@/lib/operations/journey-loop";
import { ModeProvider } from "@/lib/mode-context";
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

function renderSellerHomeWithPersona(personaId: "growth" | "leakage" | "new" = "new") {
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

describe("Issue #234: zero-extension estimated bar CTA state", () => {
  it("pending_return_count tile documents disabled no-extension state on new-seller inventory tab", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("todays-report-tab-inventory_refunds"));

    const noExtension = screen.getByTestId(
      "report-metric-estimated-inventory_refunds-pending_return_count-no-extension",
    );
    expect(noExtension).toBeInTheDocument();
    expect(noExtension).toHaveAttribute("aria-disabled", "true");
    expect(noExtension.textContent).toMatch(/không ước tính lợi ích/i);
    expect(
      screen.queryByTestId(
        "report-metric-estimated-inventory_refunds-pending_return_count-estimated",
      ),
    ).not.toBeInTheDocument();
  });

  it("no-extension bar uses accessible disabled label not silent div-only chart", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("todays-report-tab-inventory_refunds"));

    const noExtension = screen.getByTestId(
      "report-metric-estimated-inventory_refunds-pending_return_count-no-extension",
    );
    expect(noExtension.tagName).toBe("P");
    expect(noExtension).toHaveAttribute("aria-disabled", "true");
    expect(noExtension.textContent?.length).toBeGreaterThan(10);
  });

  it("pending_return_count with workflow link offers Juli suggestion-only path when extension is zero", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("todays-report-tab-inventory_refunds"));

    const expandToggle = await screen.findByTestId(
      "report-metric-suggestion-expand-inventory_refunds-pending_return_count",
    );
    await user.click(expandToggle);

    const cta = screen.getByTestId(
      "report-metric-cta-inventory_refunds-pending_return_count",
    );
    expect(cta).toHaveAttribute(
      "href",
      buildDecisionsHighlightLink("refund_spike_detection"),
    );

    const journeyLink = resolveJourneyLinkForMetric(
      "inventory_refunds",
      "pending_return_count",
    );
    expect(journeyLink?.reasonTemplate).toBeTruthy();
  });

  it("does not regress linked metrics with non-zero extension on leakage inventory tab", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("leakage");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("todays-report-tab-inventory_refunds"));

    expect(
      screen.getByTestId(
        "report-metric-estimated-inventory_refunds-low_stock_rate-estimated",
      ),
    ).toHaveAttribute("href", buildDecisionsHighlightLink("stockout_prevention"));
    expect(
      screen.getByTestId(
        "report-metric-estimated-inventory_refunds-refund_rate_7d-estimated",
      ),
    ).toHaveAttribute("href", buildDecisionsHighlightLink("refund_spike_detection"));
    expect(
      screen.queryByTestId(
        "report-metric-estimated-inventory_refunds-low_stock_rate-no-extension",
      ),
    ).not.toBeInTheDocument();
  });

  it("does not regress growth revenue estimated bar link", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-estimated-revenue_growth-revenue_7d-estimated"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("report-metric-estimated-revenue_growth-revenue_7d-estimated"),
    ).toHaveAttribute("href", buildDecisionsHighlightLink("budget_optimization"));
    expect(
      screen.queryByTestId(
        "report-metric-estimated-revenue_growth-revenue_7d-no-extension",
      ),
    ).not.toBeInTheDocument();
  });
});
