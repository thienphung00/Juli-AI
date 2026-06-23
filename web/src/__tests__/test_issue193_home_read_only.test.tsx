/**
 * Issue #193 — Home read-only shell: shop info, health, report, progress (ADR-028 P1.8-9)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { ModeProvider } from "@/lib/mode-context";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { WORKFLOW_ENTRIES } from "@/lib/seller-workflows";
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
  it("shows shop info, health, today's report, and recent progress sections", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("shop-info-card")).toBeInTheDocument();
    expect(screen.getByTestId("shop-health-card")).toBeInTheDocument();
    expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    expect(screen.getByTestId("recent-progress-card")).toBeInTheDocument();
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

  it("persona switching updates shop info and progress items", async () => {
    const user = userEvent.setup();
    renderSellerHome();

    const newPersona = loadPersona("new");
    await waitFor(() => {
      expect(screen.getByTestId("shop-info-card")).toHaveTextContent(newPersona.profile.shop_name);
    });

    const leakagePersona = loadPersona("leakage");
    await user.click(screen.getByRole("button", { name: /Rò rỉ doanh thu/i }));

    await waitFor(() => {
      expect(screen.getByTestId("shop-info-card")).toHaveTextContent(
        leakagePersona.profile.shop_name,
      );
    });

    expect(localStorage.getItem(DEMO_PERSONA_STORAGE_KEY)).toBe("leakage");
    expect(screen.getByTestId("shop-info-status")).toHaveTextContent("Hoạt động");
    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.getByTestId("recent-progress-card")).toBeInTheDocument();
  });

  it("shows active workflow label from stage router in page header", async () => {
    renderSellerHome();

    await waitFor(() => {
      const header = screen.getByRole("banner");
      expect(within(header).getByText(WORKFLOW_ENTRIES.new.label)).toBeInTheDocument();
    });
  });
});
