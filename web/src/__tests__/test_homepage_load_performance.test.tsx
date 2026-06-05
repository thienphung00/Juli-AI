/**
 * AC2 — Seller home shell loads workflow UI with mock persona data (#118).
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
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

function renderSellerHome() {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <HomePage uiOnly={false} />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

describe("AC2: Seller home shell modules", () => {
  it("renders workflow breadcrumb and task queue", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("workflow-breadcrumb")).toBeInTheDocument();
    });

    expect(screen.getByTestId("task-queue")).toBeInTheDocument();
    expect(screen.getByTestId("seller-shop-summary")).toBeInTheDocument();
  });

  it("displays shop GMV with VND formatting", async () => {
    const persona = loadPersona("new");
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("seller-gmv-30d")).toBeInTheDocument();
    });

    expect(screen.getByTestId("seller-gmv-30d")).toHaveTextContent(/₫/);
    expect(screen.getByText(persona.profile.shop_name)).toBeInTheDocument();
  });

  it("shows workflow tasks for default persona", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("task-queue-list")).toBeInTheDocument();
    });

    expect(screen.getAllByTestId("task-card").length).toBeGreaterThanOrEqual(1);
  });

  it("shows active workflow label in header subtitle", async () => {
    renderSellerHome();

    await waitFor(() => {
      const header = screen.getByRole("banner");
      expect(within(header).getByText("Copilot Người Bán Mới")).toBeInTheDocument();
    });
  });
});
