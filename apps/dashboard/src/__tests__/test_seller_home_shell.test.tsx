/**
 * Issue #118 — Seller home shell — routing + chart-first layout
 * Issue #181 — Operations pipeline shell replaces copilot-first layout
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { ModeProvider } from "@/lib/mode-context";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import { clearOperationsApprovalSession } from "@/lib/operations/approval-session";
import { clearTaskExecutorSession } from "@/lib/task-executor";

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

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTaskExecutorSession();
  clearOperationsApprovalSession();
  document.documentElement.className = "";
});

async function assertPersonaHomeLayout(personaId: "new" | "leakage" | "growth") {
  const persona = loadPersona(personaId);

  await waitFor(() => {
    expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
  });

  const header = screen.getByRole("banner");
  expect(within(header).getByTestId("shop-info-card")).toHaveTextContent(
    persona.profile.shop_name,
  );
  expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
  expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
  expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
  expect(screen.queryByTestId("persona-switcher")).not.toBeInTheDocument();
  expect(within(header).queryByText(/Copilot/i)).not.toBeInTheDocument();
}

describe("Issue #118 / #181 / #193: seller home shell", () => {
  it("lands seller in read-only home summary shell instead of legacy recommendation feed", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    expect(within(screen.getByRole("banner")).getByTestId("shop-info-card")).toBeInTheDocument();
    expect(screen.getByTestId("shop-health-card")).toBeInTheDocument();
    expect(screen.queryByTestId("operations-pipeline-shell")).not.toBeInTheDocument();
    expect(screen.queryByTestId("home-hero-matches")).not.toBeInTheDocument();
    expect(screen.queryByTestId("gmv-card")).not.toBeInTheDocument();
  });

  it("shows shop name and status in page header instead of workflow copilot label", async () => {
    renderSellerHome("new");

    await waitFor(() => {
      const header = screen.getByRole("banner");
      expect(within(header).getByTestId("shop-info-card")).toBeInTheDocument();
    });

    const header = screen.getByRole("banner");
    expect(within(header).queryByText(/Copilot/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("shop-info-status")).toHaveTextContent("Đang thử nghiệm");
  });

  it("integration: new persona shows probation shop status in header", async () => {
    renderSellerHome("new");
    await assertPersonaHomeLayout("new");
    expect(screen.getByTestId("shop-info-status")).toHaveTextContent("Đang thử nghiệm");
  });

  it("integration: leakage persona shows active shop status in header", async () => {
    renderSellerHome("leakage");
    await assertPersonaHomeLayout("leakage");
    expect(screen.getByTestId("shop-info-status")).toHaveTextContent("Hoạt động");
  });

  it("integration: growth persona loads chart-first home summary", async () => {
    renderSellerHome("growth");
    await assertPersonaHomeLayout("growth");
  });

  it("shows shop name in header shop info", async () => {
    const persona = loadPersona("new");
    renderSellerHome("new");

    await waitFor(() => {
      expect(within(screen.getByRole("banner")).getByTestId("shop-info-card")).toHaveTextContent(
        persona.profile.shop_name,
      );
    });
  });
});
