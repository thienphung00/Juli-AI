/**
 * Issue #194 — Today's Report domain cards with animated domain switcher (ADR-014 P1.8-9)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomePage } from "@/components/HomePage";
import { TodaysReportPanel } from "@/components/home/todays-report";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadOperationalModelForPersona } from "@/lib/mock-data/operations";
import { ModeProvider } from "@/lib/mode-context";
import {
  REPORT_DOMAIN_IDS,
  buildDomainReportSummary,
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

function renderSellerHome() {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <HomePage uiOnly />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

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

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
  mockMatchMedia(false);
});

describe("Issue #194: Today's Report domain cards", () => {
  it("renders three domain tabs on Home with shop info in header", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    const header = screen.getByRole("banner");
    const shell = screen.getByTestId("home-summary-shell");
    const report = screen.getByTestId("todays-report-panel");
    const shopHealth = screen.getByTestId("shop-health-card");

    expect(within(header).getByTestId("shop-info-card")).toBeInTheDocument();
    expect(shell.contains(report)).toBe(true);
    expect(shell.contains(shopHealth)).toBe(true);
    expect(
      report.compareDocumentPosition(shopHealth) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();

    for (const domainId of REPORT_DOMAIN_IDS) {
      expect(screen.getByTestId(`todays-report-tab-${domainId}`)).toBeInTheDocument();
    }
  });

  it("updates visible card content when switching domains", async () => {
    const user = userEvent.setup();
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel-product_listings")).toBeInTheDocument();
    });

    expect(screen.getByTestId("todays-report-card-product_listings")).toBeInTheDocument();
    expect(screen.queryByTestId("todays-report-card-inventory_refunds")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("todays-report-tab-inventory_refunds"));

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel-inventory_refunds")).toBeInTheDocument();
    });

    expect(screen.getByTestId("todays-report-card-inventory_refunds")).toBeInTheDocument();
    expect(screen.queryByTestId("todays-report-card-product_listings")).not.toBeInTheDocument();

    const inventorySummary = buildDomainReportSummary(
      "inventory_refunds",
      loadOperationalModelForPersona("new"),
    );
    expect(screen.getByTestId("todays-report-status-inventory_refunds")).toHaveTextContent(
      inventorySummary.statusLabel,
    );
  });

  it("shows inventory and refunds metrics on consolidated tab", async () => {
    const user = userEvent.setup();
    const model = loadOperationalModelForPersona("leakage");

    render(
      <TodaysReportPanel model={model} profile="MID_LARGE_SHOP" />,
    );

    await user.click(screen.getByTestId("todays-report-tab-inventory_refunds"));

    expect(screen.getByTestId("todays-report-card-inventory_refunds")).toBeInTheDocument();
    expect(
      screen.getByTestId("report-metric-chart-inventory_refunds-low_stock_rate"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("disables card animation when prefers-reduced-motion is reduce", async () => {
    mockMatchMedia(true);

    render(
      <TodaysReportPanel
        model={loadOperationalModelForPersona("leakage")}
        profile="MID_LARGE_SHOP"
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-card-revenue_growth")).toBeInTheDocument();
    });

    expect(screen.getByTestId("todays-report-card-revenue_growth")).toHaveAttribute(
      "data-animate",
      "false",
    );
    expect(screen.getByTestId("todays-report-card-revenue_growth")).not.toHaveClass(
      "todays-report-card-animate",
    );
  });

  it("keeps switcher usable at 375px width with horizontally scrollable tabs", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-switcher")).toBeInTheDocument();
    });

    const switcher = screen.getByTestId("todays-report-switcher");
    expect(switcher.className).toMatch(/overflow-x-auto/);

    Object.defineProperty(switcher, "clientWidth", { configurable: true, value: 375 });

    for (const domainId of REPORT_DOMAIN_IDS) {
      const tab = screen.getByTestId(`todays-report-tab-${domainId}`);
      expect(within(switcher).getByTestId(`todays-report-tab-${domainId}`)).toBeVisible();
      expect(tab.textContent?.length ?? 0).toBeGreaterThan(0);
    }
  });
});
