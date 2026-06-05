/**
 * Alerts — mode-aware feed consistent in alert bell (issue #95: Home uses match hero, not banners)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomePage } from "@/components/HomePage";
import { ModeProvider } from "@/lib/mode-context";
import {
  SELLER_LOW_STOCK_LANEIGE,
  formatInventoryRiskMessage,
  getMockWorkspaceAlerts,
} from "@/lib/mock-data/alerts";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import * as alertsService from "@/lib/services/alerts";
import * as homeService from "@/lib/services/home";

jest.mock("@/lib/services/alerts", () => ({
  ...jest.requireActual("@/lib/services/alerts"),
  getWorkspaceAlerts: jest.fn(),
}));

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

const mockGetWorkspaceAlerts = alertsService.getWorkspaceAlerts as jest.MockedFunction<
  typeof alertsService.getWorkspaceAlerts
>;
const mockGetHomeDashboard = homeService.getHomeDashboard as jest.MockedFunction<
  typeof homeService.getHomeDashboard
>;

function setupMode(mode: "seller" | "affiliate") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, mode);
  if (mode === "seller") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";
  mockGetWorkspaceAlerts.mockImplementation(async (mode) => getMockWorkspaceAlerts(mode));
});

describe("Alerts consistency", () => {
  const laneigeMessage = formatInventoryRiskMessage(SELLER_LOW_STOCK_LANEIGE);

  describe("seller mode", () => {
    it("alert bell shows inventory alert; Home shows match hero instead of banners", async () => {
      const user = userEvent.setup();
      const { MOCK_HOME_SELLER } = jest.requireActual("@/lib/mock-data/home");
      mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_SELLER);

      setupMode("seller");

      render(
        <ModeProvider>
          <HomePage uiOnly />
        </ModeProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("home-hero-matches")).toBeInTheDocument();
      });

      expect(
        screen.queryByTestId("home-alert-card-alert-seller-inventory-laneige")
      ).not.toBeInTheDocument();

      await user.click(screen.getByTestId("alert-bell-button"));

      await waitFor(() => {
        expect(screen.getByTestId("alert-bell-drawer")).toBeInTheDocument();
      });

      const inventoryItem = screen.getByTestId(
        `alert-bell-item-alert-seller-inventory-laneige`
      );
      expect(within(inventoryItem).getByText("Tồn kho sắp hết")).toBeInTheDocument();
      expect(
        within(inventoryItem).getByTestId("alert-bell-message-alert-seller-inventory-laneige")
      ).toHaveTextContent(laneigeMessage);

      expect(screen.queryByText(/Áo thun basic/)).not.toBeInTheDocument();
    });

    it("inventory alert references prod-laneige-berry-3 with 12 units and 3-day risk", () => {
      const alerts = getMockWorkspaceAlerts("seller");
      const inventory = alerts.find((a) => a.type === "inventory_risk");

      expect(inventory).toMatchObject({
        product_id: "prod-laneige-berry-3",
        stock_units: 12,
        days_until_stockout: 3,
        product_name: "Son dưỡng môi Laneige #3 Berry",
      });
      expect(inventory?.message).toBe(laneigeMessage);
    });
  });

  describe("affiliate mode", () => {
    it("shows out-of-scope on home while header alerts remain available", async () => {
      const user = userEvent.setup();
      const { MOCK_HOME_AFFILIATE } = jest.requireActual("@/lib/mock-data/home");
      mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_AFFILIATE);

      setupMode("affiliate");

      render(
        <ModeProvider>
          <HomePage uiOnly />
        </ModeProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("affiliate-out-of-scope")).toBeInTheDocument();
      });

      expect(screen.queryByTestId("home-affiliate")).not.toBeInTheDocument();
      expect(screen.queryByText(/Tồn kho sắp hết/)).not.toBeInTheDocument();

      await user.click(screen.getByTestId("alert-bell-button"));

      await waitFor(() => {
        expect(screen.getByTestId("alert-bell-badge")).toHaveTextContent("3");
      });

      expect(screen.getByTestId("alert-bell-item-alert-affiliate-commission-romand")).toBeInTheDocument();
      expect(
        screen.queryByTestId("alert-bell-item-alert-seller-inventory-laneige")
      ).not.toBeInTheDocument();
    });
  });
});
