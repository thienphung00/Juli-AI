/**
 * Issue #118 — Seller home shell — routing + persona switcher
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
  document.documentElement.classList.add("dark");

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
  document.documentElement.className = "";
});

describe("Issue #118: seller home shell", () => {
  it("lands seller in home shell instead of legacy recommendation feed", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("workflow-breadcrumb")).toBeInTheDocument();
    expect(screen.getByTestId("task-queue")).toBeInTheDocument();
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

  it("shows active workflow label from stage router", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("workflow-breadcrumb")).toHaveTextContent(
        WORKFLOW_ENTRIES.new.label,
      );
    });

    expect(screen.getByTestId("workflow-stage")).toHaveAttribute("data-stage", "new");
  });

  it("integration: switching persona changes visible workflow and stage", async () => {
    const user = userEvent.setup();
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("workflow-stage")).toHaveAttribute("data-stage", "new");
    });

    const leakagePersona = loadPersona("leakage");
    await user.click(screen.getByRole("button", { name: /Rò rỉ doanh thu/i }));

    await waitFor(() => {
      expect(screen.getByTestId("workflow-breadcrumb")).toHaveTextContent(
        WORKFLOW_ENTRIES.leakage.label,
      );
    });

    expect(screen.getByTestId("workflow-stage")).toHaveAttribute("data-stage", "leakage");
    expect(screen.getByText(leakagePersona.profile.shop_name)).toBeInTheDocument();
    expect(localStorage.getItem(DEMO_PERSONA_STORAGE_KEY)).toBe("leakage");
  });

  it.each([
    ["new", "new", WORKFLOW_ENTRIES.new.label],
    ["leakage", "leakage", WORKFLOW_ENTRIES.leakage.label],
    ["growth", "growth", WORKFLOW_ENTRIES.growth.label],
  ] as const)(
    "integration: %s persona routes to expected workflow entry",
    async (personaId, expectedStage, expectedLabel) => {
      const user = userEvent.setup();
      localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
      renderSellerHome();

      const personaLabels = {
        new: /Người bán mới/i,
        leakage: /Rò rỉ doanh thu/i,
        growth: /Tăng trưởng/i,
      } as const;

      if (personaId !== "new") {
        await user.click(screen.getByRole("button", { name: personaLabels[personaId] }));
      }

      await waitFor(() => {
        expect(screen.getByTestId("workflow-breadcrumb")).toHaveTextContent(expectedLabel);
      });

      expect(screen.getByTestId("workflow-stage")).toHaveAttribute("data-stage", expectedStage);
      expect(screen.getByText(loadPersona(personaId).profile.shop_name)).toBeInTheDocument();
    },
  );

  it("shows shop GMV with VND formatting", async () => {
    renderSellerHome();

    const persona = loadPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("seller-shop-summary")).toHaveTextContent(
        persona.profile.shop_name,
      );
    });

    expect(screen.getByTestId("seller-gmv-30d")).toHaveTextContent(/₫/);
  });
});
