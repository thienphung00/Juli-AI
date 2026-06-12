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

async function assertPersonaUpdatesOperationsShell(personaId: "new" | "leakage" | "growth") {
  const persona = loadPersona(personaId);

  await waitFor(() => {
    expect(screen.getByTestId("operations-pipeline-shell")).toBeInTheDocument();
  });

  expect(screen.getByTestId("shop-health-hero")).toHaveTextContent(persona.profile.shop_name);
  expect(screen.getByTestId("approval-gate-toolbar")).toBeInTheDocument();
  expect(screen.getAllByTestId("clarity-card").length).toBeGreaterThan(0);

  const header = screen.getByRole("banner");
  expect(within(header).getByText(WORKFLOW_ENTRIES[personaId].label)).toBeInTheDocument();
}

describe("Issue #118 / #181: seller home shell", () => {
  it("lands seller in operations pipeline shell instead of legacy recommendation feed", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("operations-pipeline-shell")).toBeInTheDocument();
    expect(screen.getByTestId("shop-health-hero")).toBeInTheDocument();
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

  it("integration: switching persona changes shop health hero and clarity cards", async () => {
    const user = userEvent.setup();
    renderSellerHome();

    await assertPersonaUpdatesOperationsShell("new");

    const leakagePersona = loadPersona("leakage");
    await user.click(screen.getByRole("button", { name: /Rò rỉ doanh thu/i }));

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-hero")).toHaveTextContent(
        leakagePersona.profile.shop_name,
      );
    });

    expect(localStorage.getItem(DEMO_PERSONA_STORAGE_KEY)).toBe("leakage");
    expect(
      screen.getByTestId("approval-approve-refund_spike_detection"),
    ).toBeInTheDocument();
  });

  it("integration: new persona loads NEW_SHOP operations recommendations", async () => {
    renderSellerHome();
    await assertPersonaUpdatesOperationsShell("new");
    expect(screen.getByTestId("shop-health-profile")).toHaveTextContent("Shop mới");
  });

  it("integration: leakage persona loads MID_LARGE operations recommendations", async () => {
    const user = userEvent.setup();
    renderSellerHome();
    await user.click(screen.getByRole("button", { name: /Rò rỉ doanh thu/i }));
    await assertPersonaUpdatesOperationsShell("leakage");
    expect(screen.getByTestId("shop-health-profile")).toHaveTextContent("Shop trung/lớn");
  });

  it("integration: growth persona loads operations shell with clarity cards", async () => {
    const user = userEvent.setup();
    renderSellerHome();
    await user.click(screen.getByRole("button", { name: /Tăng trưởng/i }));
    await assertPersonaUpdatesOperationsShell("growth");
  });

  it("shows shop name in health hero", async () => {
    renderSellerHome();

    const persona = loadPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-hero")).toHaveTextContent(
        persona.profile.shop_name,
      );
    });
  });
});
