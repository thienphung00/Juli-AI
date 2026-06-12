/**
 * Issue #79 — Home control center (mode-aware KPIs + inline AI + alerts)
 * Issue #118 — Seller home shell replaces legacy seller control center
 */
import { render, screen, waitFor } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_MODE_STORAGE_KEY, applyWorkspaceTheme } from "@/lib/workspace-mode";
import * as homeService from "@/lib/services/home";

jest.mock("@/lib/services/home", () => ({
  ...jest.requireActual("@/lib/services/home"),
  getHomeDashboard: jest.fn(),
}));

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

const mockGetHomeDashboard = homeService.getHomeDashboard as jest.MockedFunction<
  typeof homeService.getHomeDashboard
>;

function renderHome(mode: "seller" | "affiliate", uiOnly = true) {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, mode);
  applyWorkspaceTheme(mode);

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <HomePage uiOnly={uiOnly} />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";
});

describe("Home control center (#79, #118)", () => {
  describe("seller mode", () => {
    it("renders seller workflow shell as primary entry", async () => {
      renderHome("seller");

      await waitFor(() => {
        expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
      });

      expect(document.documentElement.classList.contains("dark")).toBe(false);
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
      expect(screen.getByTestId("shop-info-card")).toBeInTheDocument();
      expect(screen.queryByTestId("home-hero-matches")).not.toBeInTheDocument();
    });
  });

  describe("affiliate mode", () => {
    it("renders dark theme with out-of-scope instead of seller workflows", async () => {
      const { MOCK_HOME_AFFILIATE } = jest.requireActual("@/lib/mock-data/home");
      mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_AFFILIATE);

      renderHome("affiliate");

      await waitFor(() => {
        expect(screen.getByTestId("affiliate-out-of-scope")).toBeInTheDocument();
      });

      expect(document.documentElement.classList.contains("dark")).toBe(true);
      expect(screen.queryByTestId("home-affiliate")).not.toBeInTheDocument();
      expect(screen.queryByTestId("home-hero-matches")).not.toBeInTheDocument();
      expect(screen.queryByTestId("commission-card")).not.toBeInTheDocument();
    });
  });
});
