/**
 * AC2 — Seller home shell loads operations pipeline UI with mock persona data (#118, #181).
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
  it("renders read-only home summary shell with health hero and decision preview", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("shop-info-card")).toBeInTheDocument();
    expect(screen.getByTestId("recent-progress-card")).toBeInTheDocument();
    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
  });

  it("displays shop name in health hero", async () => {
    const persona = loadPersona("new");
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("shop-info-card")).toHaveTextContent(
        persona.profile.shop_name,
      );
    });
  });

  it("shows recent progress items for default persona", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getAllByTestId("recent-progress-item").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows active workflow label in header subtitle", async () => {
    renderSellerHome();

    await waitFor(() => {
      const header = screen.getByRole("banner");
      expect(within(header).getByText("Copilot Người Bán Mới")).toBeInTheDocument();
    });
  });
});
