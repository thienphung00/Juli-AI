/**
 * Issue #81 — Operations hub (role-based sub-tabs: Seller vs Affiliate)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperationPage } from "@/components/OperationPage";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import * as operationService from "@/lib/services/operation";

jest.mock("@/lib/services/operation", () => ({
  ...jest.requireActual("@/lib/services/operation"),
  getOperationData: jest.fn(),
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
  usePathname: () => "/operation",
}));

const mockGetOperationData = operationService.getOperationData as jest.MockedFunction<
  typeof operationService.getOperationData
>;

function renderOperation(mode: "seller" | "affiliate", uiOnly = true) {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, mode);
  if (mode === "seller") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }

  return render(
    <ModeProvider>
      <OperationPage uiOnly={uiOnly} />
    </ModeProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";
});

describe("Operations hub (#81)", () => {
  describe("seller mode", () => {
    it("shows 4 sub-tabs including Creator", async () => {
      const { MOCK_OPERATION_SELLER } = jest.requireActual(
        "@/lib/mock-data/operation-seller"
      );
      mockGetOperationData.mockResolvedValue(MOCK_OPERATION_SELLER);

      renderOperation("seller");

      await waitFor(() => {
        expect(screen.getByTestId("operation-hub-seller")).toBeInTheDocument();
      });

      const tabBar = screen.getByTestId("operation-sub-tabs");
      expect(within(tabBar).getByRole("tab", { name: "Sản phẩm" })).toBeInTheDocument();
      expect(within(tabBar).getByRole("tab", { name: "Creator" })).toBeInTheDocument();
      expect(within(tabBar).getByRole("tab", { name: "Đơn hàng" })).toBeInTheDocument();
      expect(within(tabBar).getByRole("tab", { name: "Hoàn trả" })).toBeInTheDocument();
      expect(within(tabBar).getAllByRole("tab")).toHaveLength(4);
    });

    it("shows GMV and ROI fields on products tab", async () => {
      const { MOCK_OPERATION_SELLER } = jest.requireActual(
        "@/lib/mock-data/operation-seller"
      );
      mockGetOperationData.mockResolvedValue(MOCK_OPERATION_SELLER);

      renderOperation("seller");

      await waitFor(() => {
        expect(screen.getByTestId("operation-panel-products")).toBeInTheDocument();
      });

      const panel = screen.getByTestId("operation-panel-products");
      expect(within(panel).getByText(/GMV tháng này/)).toBeInTheDocument();
      expect(within(panel).getByText(/Son Laneige #3 Berry/)).toBeInTheDocument();
      expect(within(panel).getByText(/ROI 340%/)).toBeInTheDocument();
    });
  });

  describe("affiliate mode", () => {
    it("shows out-of-scope instead of operation hub", async () => {
      const { MOCK_OPERATION_AFFILIATE } = jest.requireActual(
        "@/lib/mock-data/operation-affiliate"
      );
      mockGetOperationData.mockResolvedValue(MOCK_OPERATION_AFFILIATE);

      renderOperation("affiliate");

      await waitFor(() => {
        expect(screen.getByTestId("affiliate-out-of-scope")).toBeInTheDocument();
      });

      expect(screen.queryByTestId("operation-hub-affiliate")).not.toBeInTheDocument();
      expect(screen.queryByTestId("operation-sub-tabs")).not.toBeInTheDocument();
    });

    it("does not render operation panels in affiliate mode", async () => {
      const { MOCK_OPERATION_AFFILIATE } = jest.requireActual(
        "@/lib/mock-data/operation-affiliate"
      );
      mockGetOperationData.mockResolvedValue(MOCK_OPERATION_AFFILIATE);

      renderOperation("affiliate");

      await waitFor(() => {
        expect(screen.getByTestId("affiliate-out-of-scope")).toBeInTheDocument();
      });

      expect(screen.queryByTestId("operation-panel-products")).not.toBeInTheDocument();
    });
  });

  describe("UI-only mode", () => {
    it("loads operation data via service without calling api-client", async () => {
      mockGetOperationData.mockImplementation(async (mode) => {
        const { getMockOperationData } = jest.requireActual("@/lib/services/operation");
        return getMockOperationData(mode);
      });

      renderOperation("seller", true);

      await waitFor(() => {
        expect(mockGetOperationData).toHaveBeenCalledWith("seller");
      });

      expect(screen.getByTestId("operation-hub-seller")).toBeInTheDocument();
      expect(screen.getByText(/Son Laneige #3 Berry/)).toBeInTheDocument();
    });
  });

  describe("sub-tab navigation", () => {
    it("switches panels when clicking orders tab", async () => {
      const user = userEvent.setup();
      const { MOCK_OPERATION_SELLER } = jest.requireActual(
        "@/lib/mock-data/operation-seller"
      );
      mockGetOperationData.mockResolvedValue(MOCK_OPERATION_SELLER);

      renderOperation("seller");

      await waitFor(() => {
        expect(screen.getByTestId("operation-panel-products")).toBeInTheDocument();
      });

      await user.click(screen.getByRole("tab", { name: "Đơn hàng" }));

      expect(screen.getByTestId("operation-panel-orders")).toBeInTheDocument();
      expect(screen.getByText("DH-20260527-8821")).toBeInTheDocument();
    });
  });
});
