/**
 * Issue #219 — Home inbound highlight: close Anticipation → Reward return path (P1.8-10)
 */
import { render, screen, waitFor } from "@testing-library/react";
import { DecisionsPage } from "@/components/DecisionsPage";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import {
  buildHomeHighlightLink,
  getJourneyLink,
  resolveHomeHighlight,
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

const mockSearchParams = new URLSearchParams();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/",
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

function renderSellerHome(personaId: "growth" | "leakage" | "new" = "growth") {
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

function renderDecisions(personaId: "growth" | "new" = "growth") {
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

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
  mockMatchMedia(false);
  mockSearchParams.forEach((_, key) => {
    mockSearchParams.delete(key);
  });
  Element.prototype.scrollIntoView = jest.fn();
});

describe("Issue #219: Home inbound highlight — report domain tabs", () => {
  it("selects Tăng trưởng tab and highlights Doanh thu 7 ngày for revenue_growth:revenue_7d", async () => {
    mockSearchParams.set("highlight", "revenue_growth:revenue_7d");
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel-revenue_growth")).toBeInTheDocument();
      expect(
        screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d"),
      ).toHaveAttribute("data-highlighted", "true");
    });

    expect(screen.getByTestId("todays-report-tab-revenue_growth")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("selects Tăng trưởng tab and highlights ROAS for revenue_growth:roas", async () => {
    mockSearchParams.set("highlight", "revenue_growth:roas");
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel-revenue_growth")).toBeInTheDocument();
      expect(screen.getByTestId("report-metric-chart-revenue_growth-roas")).toHaveAttribute(
        "data-highlighted",
        "true",
      );
    });

    expect(screen.queryByTestId("todays-report-tab-advertising")).not.toBeInTheDocument();
  });

  it("selects Tồn kho & Hoàn tiền and highlights refund rate for inventory_refunds:refund_rate_7d", async () => {
    mockSearchParams.set("highlight", "inventory_refunds:refund_rate_7d");
    renderSellerHome("leakage");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel-inventory_refunds")).toBeInTheDocument();
      expect(
        screen.getByTestId("report-metric-chart-inventory_refunds-refund_rate_7d"),
      ).toHaveAttribute("data-highlighted", "true");
    });

    expect(screen.getByTestId("todays-report-tab-inventory_refunds")).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

describe("Issue #219: Home inbound highlight — shop health", () => {
  it("scrolls to AHR bar for shop_health:ahr on new-seller persona", async () => {
    mockSearchParams.set("highlight", "shop_health:ahr");
    renderSellerHome("new");

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-ahr")).toHaveAttribute("data-highlighted", "true");
    });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });
});

describe("Issue #219: Home inbound highlight — edge cases", () => {
  it("ignores invalid ?highlight=foo silently", async () => {
    mockSearchParams.set("highlight", "foo");
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    const charts = screen.getAllByTestId(/^report-metric-chart-/);
    for (const chart of charts) {
      expect(chart).not.toHaveAttribute("data-highlighted", "true");
    }

    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it("scrolls without pulse when prefers-reduced-motion is reduce", async () => {
    mockMatchMedia(true);
    mockSearchParams.set("highlight", "revenue_growth:revenue_7d");
    renderSellerHome("growth");

    await waitFor(() => {
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "auto" }),
    );

    expect(
      screen.getByTestId("report-metric-chart-revenue_growth-revenue_7d"),
    ).not.toHaveAttribute("data-highlighted", "true");
  });

  it("keeps Home read-only — no approve CTAs when highlight param is present", async () => {
    mockSearchParams.set("highlight", "revenue_growth:roas");
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId(/^approval-approve-/)).not.toBeInTheDocument();
  });
});

describe("Issue #219: Decisions Anticipation → Home integration", () => {
  it("lands on correct Home tab with data-highlighted from clarity card home link", async () => {
    mockSearchParams.delete("highlight");
    renderDecisions("growth");

    await waitFor(() => {
      expect(screen.getByTestId("clarity-card-home-link-budget_optimization")).toBeInTheDocument();
    });

    const homeLink = screen.getByTestId("clarity-card-home-link-budget_optimization");
    const href = homeLink.getAttribute("href");
    expect(href).toBe(buildHomeHighlightLink(resolveHomeHighlight("budget_optimization")!));

    const highlightParam = new URL(href!, "http://localhost").searchParams.get("highlight");
    mockSearchParams.set("highlight", highlightParam!);

    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel-revenue_growth")).toBeInTheDocument();
      expect(screen.getByTestId("report-metric-chart-revenue_growth-roas")).toHaveAttribute(
        "data-highlighted",
        "true",
      );
    });

    expect(getJourneyLink("budget_optimization")?.metricKey).toBe("roas");
  });
});
