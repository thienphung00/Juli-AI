/**
 * Issue #226 — Home chart-first IA: remove preview/Tiến độ, reorder bands (PRD B1.1)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
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

function renderSellerHome(personaId: "new" | "leakage" | "growth" = "new") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <HomePage uiOnly />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

function assertBandOrder() {
  const header = screen.getByRole("banner");
  const shell = screen.getByTestId("home-summary-shell");
  const shopInfo = within(header).getByTestId("shop-info-card");
  const report = screen.getByTestId("todays-report-panel");
  const shopHealth = screen.getByTestId("shop-health-card");

  expect(shell.contains(report)).toBe(true);
  expect(shell.contains(shopHealth)).toBe(true);
  expect(shell.contains(shopInfo)).toBe(false);
  expect(
    report.compareDocumentPosition(shopHealth) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    shopInfo.compareDocumentPosition(report) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
});

describe("Issue #226: Home chart-first 3-band layout", () => {
  it("does not render decision preview, recent progress, or demo persona controls", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("decision-preview-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("persona-switcher")).not.toBeInTheDocument();
    expect(screen.queryByTestId("demo-controls-button")).not.toBeInTheDocument();
  });

  it("places shop info in header then today's report and shop health in body", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    assertBandOrder();
  });

  it("integration: growth persona renders chart-first layout without regression", async () => {
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();
    assertBandOrder();
    expect(screen.getByTestId("todays-report-tab-revenue_growth")).toBeInTheDocument();
  });

  it("integration: new-seller persona renders chart-first layout without regression", async () => {
    renderSellerHome("new");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();
    assertBandOrder();
    expect(screen.getByTestId("shop-info-status")).toHaveTextContent("Đang thử nghiệm");
  });
});
