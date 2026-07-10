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
  it("renders chart-first home summary shell without task preview cards", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(within(screen.getByRole("banner")).getByTestId("shop-info-card")).toBeInTheDocument();
    expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("recent-progress-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
  });

  it("displays shop name in header", async () => {
    const persona = loadPersona("new");
    renderSellerHome();

    await waitFor(() => {
      expect(within(screen.getByRole("banner")).getByTestId("shop-info-card")).toHaveTextContent(
        persona.profile.shop_name,
      );
    });
  });

  it("does not show recent progress items on Home (moved to Decisions)", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("recent-progress-item")).not.toBeInTheDocument();
  });

  it("shows shop status in header instead of workflow copilot subtitle", async () => {
    renderSellerHome();

    await waitFor(() => {
      const header = screen.getByRole("banner");
      expect(within(header).getByTestId("shop-info-status")).toHaveTextContent("Đang thử nghiệm");
      expect(within(header).queryByText(/Copilot/i)).not.toBeInTheDocument();
    });
  });
});
