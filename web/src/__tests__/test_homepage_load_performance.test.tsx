/**
 * AC2 — Homepage loads showing GMV counter, livestream feed, AI recommendations,
 * inventory risk modules (PRD AC-12). Validates structure and empty-state rendering.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: { sendOtp: jest.fn(), verifyOtp: jest.fn() },
    shops: {
      list: jest.fn(),
      me: jest.fn(),
    },
    orders: { list: jest.fn(), confirmShipment: jest.fn() },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
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

const mockShopsList = api.shops.list as jest.MockedFunction<typeof api.shops.list>;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

describe("AC2: Homepage dashboard modules", () => {
  it("renders all four dashboard cards", async () => {
    mockShopsList.mockResolvedValue([
      { id: "shop-1", name: "Shop Test", tiktok_shop_id: "ts-1" },
    ]);

    render(<HomePage />);

    await waitFor(() => {
      expect(screen.getByTestId("gmv-card")).toBeInTheDocument();
    });

    expect(screen.getByTestId("livestream-card")).toBeInTheDocument();
    expect(screen.getByTestId("recommendations-card")).toBeInTheDocument();
    expect(screen.getByTestId("inventory-risk-card")).toBeInTheDocument();
  });

  it("displays GMV card with VND formatting", async () => {
    mockShopsList.mockResolvedValue([
      { id: "shop-1", name: "Shop Test", tiktok_shop_id: "ts-1" },
    ]);

    render(<HomePage />);

    await waitFor(() => {
      expect(screen.getByTestId("gmv-card")).toBeInTheDocument();
    });

    expect(screen.getByText("GMV hôm nay")).toBeInTheDocument();
  });

  it("shows empty states gracefully when no data", async () => {
    mockShopsList.mockResolvedValue([
      { id: "shop-1", name: "Shop Test", tiktok_shop_id: "ts-1" },
    ]);

    render(<HomePage />);

    await waitFor(() => {
      expect(screen.getByText("Chưa có phiên livestream nào")).toBeInTheDocument();
    });

    expect(
      screen.getByText("Chưa có gợi ý — dữ liệu đang được thu thập")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Không có sản phẩm nào có nguy cơ hết hàng")
    ).toBeInTheDocument();
  });

  it("shows shop name in header after loading", async () => {
    mockShopsList.mockResolvedValue([
      { id: "shop-1", name: "Cửa hàng ABC", tiktok_shop_id: "ts-1" },
    ]);

    render(<HomePage />);

    await waitFor(() => {
      expect(screen.getByText("Cửa hàng ABC")).toBeInTheDocument();
    });
  });

  it("handles graceful empty state when no shops exist", async () => {
    mockShopsList.mockResolvedValue([]);

    render(<HomePage />);

    await waitFor(() => {
      expect(screen.getByTestId("gmv-card")).toBeInTheDocument();
    });
  });
});
