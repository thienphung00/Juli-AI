/**
 * Issue #193 — Home read-only shell: shop info, health, report, progress (ADR-014 P1.8-9)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { ModeProvider } from "@/lib/mode-context";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
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

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
});

describe("Issue #193: Home read-only shell", () => {
  it("shows shop info in header and today's report + shop health in body", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

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
    expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
  });

  it("has zero approve, reject, or approval-toolbar controls on Home (CI gate)", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-approve-all")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-approve-selected")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-select-all")).not.toBeInTheDocument();
    expect(screen.queryByTestId("operations-pipeline-shell")).not.toBeInTheDocument();
    expect(screen.queryByTestId("clarity-card")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /phê duyệt/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /từ chối/i })).not.toBeInTheDocument();
  });

  it("integration: load seller home → SPS/AHR visible → no approval UI", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-sps")).toBeInTheDocument();
    });

    const pipeline = runOperationsPipeline("new");
    const probation = pipeline.unifiedModel.probation!;

    expect(screen.getByTestId("shop-health-sps")).toHaveTextContent(/2[,.]8/);
    expect(screen.getByTestId("shop-health-ahr")).toHaveTextContent(String(probation.ahr_current));
    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("outcome-tracking-view")).not.toBeInTheDocument();
  });

  it("stored leakage persona shows active shop status in header", async () => {
    const leakagePersona = loadPersona("leakage");
    localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, "leakage");
    renderSellerHome();

    await waitFor(() => {
      expect(within(screen.getByRole("banner")).getByTestId("shop-info-card")).toHaveTextContent(
        leakagePersona.profile.shop_name,
      );
    });

    expect(screen.getByTestId("shop-info-status")).toHaveTextContent("Hoạt động");
    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();
  });

  it("shows shop info in header without workflow copilot subtitle", async () => {
    renderSellerHome();

    await waitFor(() => {
      const header = screen.getByRole("banner");
      expect(within(header).getByTestId("shop-info-card")).toBeInTheDocument();
      expect(within(header).queryByText(/Copilot/i)).not.toBeInTheDocument();
    });
  });
});
