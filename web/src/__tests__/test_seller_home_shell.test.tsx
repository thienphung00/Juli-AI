/**
 * Issue #118 — Seller home shell — routing + persona switcher
 * Issue #181 — Operations pipeline shell replaces copilot-first layout
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { ModeProvider } from "@/lib/mode-context";
import { WORKFLOW_ENTRIES } from "@/lib/seller-workflows";
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
  clearTaskExecutorSession();
  clearOperationsApprovalSession();
  document.documentElement.className = "";
});

async function assertPersonaUpdatesHomeSummaryShell(personaId: "new" | "leakage" | "growth") {
  const persona = loadPersona(personaId);

  await waitFor(() => {
    expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
  });

  expect(screen.getByTestId("shop-info-card")).toHaveTextContent(persona.profile.shop_name);
  expect(screen.getByTestId("recent-progress-card")).toBeInTheDocument();
  expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();

  const header = screen.getByRole("banner");
  expect(within(header).getByText(WORKFLOW_ENTRIES[personaId].label)).toBeInTheDocument();
}

describe("Issue #118 / #181 / #193: seller home shell", () => {
  it("lands seller in read-only home summary shell instead of legacy recommendation feed", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    expect(screen.getByTestId("shop-info-card")).toBeInTheDocument();
    expect(screen.getByTestId("shop-health-card")).toBeInTheDocument();
    expect(screen.queryByTestId("operations-pipeline-shell")).not.toBeInTheDocument();
    expect(screen.queryByTestId("home-hero-matches")).not.toBeInTheDocument();
    expect(screen.queryByTestId("gmv-card")).not.toBeInTheDocument();
  });

  it("loads mock personas in persona switcher", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("persona-switcher")).toBeInTheDocument();
    });

    const switcher = screen.getByTestId("persona-switcher");
    expect(within(switcher).getByRole("button", { name: /Người bán mới/i })).toBeInTheDocument();
    expect(within(switcher).getByRole("button", { name: /Rò rỉ doanh thu/i })).toBeInTheDocument();
    expect(within(switcher).getByRole("button", { name: /Tăng trưởng/i })).toBeInTheDocument();
  });

  it("shows active workflow label from stage router in page header", async () => {
    renderSellerHome();

    await waitFor(() => {
      const header = screen.getByRole("banner");
      expect(within(header).getByText(WORKFLOW_ENTRIES.new.label)).toBeInTheDocument();
    });
  });

  it("integration: switching persona changes shop info and progress sections", async () => {
    const user = userEvent.setup();
    renderSellerHome();

    await assertPersonaUpdatesHomeSummaryShell("new");

    const leakagePersona = loadPersona("leakage");
    await user.click(screen.getByRole("button", { name: /Rò rỉ doanh thu/i }));

    await waitFor(() => {
      expect(screen.getByTestId("shop-info-card")).toHaveTextContent(
        leakagePersona.profile.shop_name,
      );
    });

    expect(localStorage.getItem(DEMO_PERSONA_STORAGE_KEY)).toBe("leakage");
    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
  });

  it("integration: new persona shows probation shop status", async () => {
    renderSellerHome();
    await assertPersonaUpdatesHomeSummaryShell("new");
    expect(screen.getByTestId("shop-info-status")).toHaveTextContent("Đang thử nghiệm");
  });

  it("integration: leakage persona shows active shop status", async () => {
    const user = userEvent.setup();
    renderSellerHome();
    await user.click(screen.getByRole("button", { name: /Rò rỉ doanh thu/i }));
    await assertPersonaUpdatesHomeSummaryShell("leakage");
    expect(screen.getByTestId("shop-info-status")).toHaveTextContent("Hoạt động");
  });

  it("integration: growth persona loads home summary with progress section", async () => {
    const user = userEvent.setup();
    renderSellerHome();
    await user.click(screen.getByRole("button", { name: /Tăng trưởng/i }));
    await assertPersonaUpdatesHomeSummaryShell("growth");
  });

  it("shows shop name in shop info card", async () => {
    renderSellerHome();

    const persona = loadPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("shop-info-card")).toHaveTextContent(
        persona.profile.shop_name,
      );
    });
  });
});
