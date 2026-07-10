/**
 * Issue #230 — Estimated bar glow affordance + 44px whole-tile targets
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
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

describe("Issue #230: estimated glow + whole-tile targets", () => {
  it("applies glow class on estimated segment when motion is allowed", async () => {
    mockMatchMedia(false);
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-estimated-revenue_growth-revenue_7d-estimated"),
      ).toBeInTheDocument();
    });

    const estimatedLink = screen.getByTestId(
      "report-metric-estimated-revenue_growth-revenue_7d-estimated",
    );
    expect(estimatedLink).toHaveAttribute("data-estimated-glow", "on");
    expect(estimatedLink.className).toMatch(/estimated-segment-glow/);
  });

  it("disables glow class when prefers-reduced-motion is reduce", async () => {
    mockMatchMedia(true);
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-estimated-revenue_growth-revenue_7d-estimated"),
      ).toBeInTheDocument();
    });

    const estimatedLink = screen.getByTestId(
      "report-metric-estimated-revenue_growth-revenue_7d-estimated",
    );
    expect(estimatedLink).toHaveAttribute("data-estimated-glow", "off");
    expect(estimatedLink.className).not.toMatch(/estimated-segment-glow/);
  });

  it("metric tile has min-h-11 for 44px touch target at mobile viewport", async () => {
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 375,
    });

    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d")).toBeInTheDocument();
    });

    const tile = screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d");
    expect(tile.className).toMatch(/min-h-11/);
  });

  it("estimated bar touch target uses min-h-11 wrapper", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-estimated-revenue_growth-revenue_7d-touch-target"),
      ).toBeInTheDocument();
    });

    const touchTarget = screen.getByTestId(
      "report-metric-estimated-revenue_growth-revenue_7d-touch-target",
    );
    expect(touchTarget.className).toMatch(/min-h-11/);
  });

  it("keeps bar track height stable while glow animates on touch wrapper", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-estimated-revenue_growth-revenue_7d-touch-target"),
      ).toBeInTheDocument();
    });

    const touchTarget = screen.getByTestId(
      "report-metric-estimated-revenue_growth-revenue_7d-touch-target",
    );
    const track = touchTarget.querySelector('[role="group"]');
    expect(track).toHaveClass("h-3");
    expect(touchTarget.className).toMatch(/min-h-11/);
  });

  it("keyboard: Enter toggles expand and Tab reaches Decisions CTA after target expansion", async () => {
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

  it("expand toggle has focus-visible ring classes", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(
        screen.getByTestId("report-metric-suggestion-expand-revenue_growth-revenue_7d"),
      ).toBeInTheDocument();
    });

    const expandToggle = screen.getByTestId(
      "report-metric-suggestion-expand-revenue_growth-revenue_7d",
    );
    expect(expandToggle.className).toMatch(/focus-visible:ring/);
  });
});
