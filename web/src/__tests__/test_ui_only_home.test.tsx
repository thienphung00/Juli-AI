/**
 * Regression: #71 UI-only shows home UI; #70 skips API wait in UI-only mode.
 */
import { render, screen } from "@testing-library/react";
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
    isAuthenticated: false,
    isLoading: false,
    user: null,
    token: null,
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const mockShopsList = api.shops.list as jest.MockedFunction<typeof api.shops.list>;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

describe("UI-only home (#71, #70)", () => {
  it("renders dashboard modules immediately without calling shops API", () => {
    render(<HomePage uiOnly />);

    expect(mockShopsList).not.toHaveBeenCalled();
    expect(screen.getByTestId("gmv-card")).toBeInTheDocument();
    expect(screen.getByTestId("livestream-card")).toBeInTheDocument();
    expect(screen.getByTestId("recommendations-card")).toBeInTheDocument();
    expect(screen.getByTestId("inventory-risk-card")).toBeInTheDocument();
  });

  it("shows demo shop name in header", () => {
    render(<HomePage uiOnly />);

    expect(screen.getByText("Cửa hàng demo")).toBeInTheDocument();
  });
});
