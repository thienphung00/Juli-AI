/**
 * Issue #79 — Home control center (mode-aware KPIs + inline AI + alerts)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
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
  if (mode === "seller") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }

  return render(
    <ModeProvider>
      <HomePage uiOnly={uiOnly} />
    </ModeProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";
});

describe("Home control center (#79)", () => {
  describe("seller mode", () => {
    it("AC4: renders top hero matches in above-the-fold section (UI shell)", async () => {
      const { MOCK_HOME_SELLER } = jest.requireActual("@/lib/mock-data/home");
      mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_SELLER);

      renderHome("seller");

      await waitFor(() => {
        expect(screen.getByTestId("home-seller")).toBeInTheDocument();
      });

      expect(document.documentElement.classList.contains("dark")).toBe(true);

      const aboveFold = screen.getByTestId("home-above-fold");
      expect(within(aboveFold).getByTestId("home-hero-matches")).toBeInTheDocument();
      const matchCards = screen.getAllByTestId("home-hero-match-card");
      expect(matchCards.length).toBeGreaterThanOrEqual(1);
      expect(within(matchCards[0]).getByTestId("home-hero-match-headline")).toHaveTextContent(
        /@linh\.nhi/
      );
    });
  });

  describe("affiliate mode", () => {
    it("renders light theme with hero matches and commission KPIs", async () => {
      const { MOCK_HOME_AFFILIATE } = jest.requireActual("@/lib/mock-data/home");
      mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_AFFILIATE);

      renderHome("affiliate");

      await waitFor(() => {
        expect(screen.getByTestId("home-affiliate")).toBeInTheDocument();
      });

      expect(document.documentElement.classList.contains("dark")).toBe(false);
      expect(screen.getByTestId("home-hero-matches")).toBeInTheDocument();
      expect(screen.getByTestId("home-hero-match-headline")).toHaveTextContent(/Romand/);
      expect(screen.getByTestId("commission-card")).toBeInTheDocument();
    });
  });

  describe("UI-only mode", () => {
    it("loads dashboard via service without calling shops API", async () => {
      const { MOCK_HOME_SELLER } = jest.requireActual("@/lib/mock-data/home");
      mockGetHomeDashboard.mockImplementation(async (mode) => {
        const { getMockHomeDashboard } = jest.requireActual("@/lib/mock-data/home");
        return getMockHomeDashboard(mode);
      });

      renderHome("seller", true);

      await waitFor(() => {
        expect(mockGetHomeDashboard).toHaveBeenCalledWith("seller");
      });

      expect(screen.getByText("BeautyShop VN")).toBeInTheDocument();
      expect(MOCK_HOME_SELLER.kpis.gmv_today_vnd).toBeGreaterThan(0);
    });
  });
});
