/**
 * AC2 — Alert history feed shows past alerts with status, delivery channel, and timestamps
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AlertsPage } from "@/components/AlertsPage";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: { sendOtp: jest.fn(), verifyOtp: jest.fn() },
    shops: { list: jest.fn(), me: jest.fn() },
    orders: { list: jest.fn(), confirmShipment: jest.fn() },
    products: { list: jest.fn() },
    inventory: { list: jest.fn() },
    livestreams: { list: jest.fn() },
    creators: { list: jest.fn() },
    alerts: { history: jest.fn(), upsertConfig: jest.fn() },
    recommendations: { list: jest.fn() },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
      this.name = "ApiError";
    }
  },
}));

jest.mock("next/navigation", () => ({
  usePathname: () => "/alerts",
}));

const mockHistory = api.alerts.history as jest.MockedFunction<typeof api.alerts.history>;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("access_token", "test-token");
  localStorage.setItem("active_shop_id", "shop-1");
});

describe("AC2: Alert history feed", () => {
  it("renders alert history items with status/channel/timestamp", async () => {
    mockHistory.mockResolvedValue({
      items: [
        {
          id: "hist-1",
          alert_type: "inventory_low_stock",
          channel: "fcm",
          triggered_at: "2024-06-15T10:00:00Z",
          status: "sent",
          payload: { days_until_depletion: 3 },
        },
      ],
      next_cursor: null,
    });

    const user = userEvent.setup();
    render(<AlertsPage />);

    await user.click(screen.getByRole("button", { name: "Lịch sử" }));

    await waitFor(() => {
      expect(screen.getByTestId("alerts-history")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByTestId("alerts-history-list")).toBeInTheDocument();
    });

    expect(screen.getByText("Tồn kho sắp hết")).toBeInTheDocument();
    expect(screen.getByText("Đã gửi")).toBeInTheDocument();
    expect(screen.getByText(/Kênh: FCM/i)).toBeInTheDocument();
  });
});

