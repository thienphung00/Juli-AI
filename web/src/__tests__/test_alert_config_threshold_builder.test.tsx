/**
 * AC1 — Alert config page allows setting/editing thresholds per alert type per shop
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

const mockUpsertConfig = api.alerts.upsertConfig as jest.MockedFunction<
  typeof api.alerts.upsertConfig
>;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("access_token", "test-token");
  localStorage.setItem("active_shop_id", "shop-1");
});

describe("AC1: Alert config threshold builder", () => {
  it("allows editing thresholds and saving config", async () => {
    mockUpsertConfig.mockResolvedValue({
      rules: [
        {
          id: "cfg-1",
          alert_type: "inventory_low_stock",
          channel: "fcm",
          is_active: true,
          threshold: { days_until_depletion: 5 },
        },
      ],
    });

    const user = userEvent.setup();
    render(<AlertsPage />);

    expect(screen.getByTestId("alerts-config")).toBeInTheDocument();
    expect(screen.getByTestId("alerts-rule-builder")).toBeInTheDocument();

    const thresholdInput = screen.getAllByLabelText(/Ngưỡng rule/i)[0];
    await user.clear(thresholdInput);
    await user.type(thresholdInput, "5");

    const addBtn = screen.getByTestId("add-alert-rule");
    await user.click(addBtn);
    expect(screen.getAllByTestId("alert-rule-card").length).toBeGreaterThanOrEqual(2);

    const saveBtn = screen.getByTestId("save-alert-config");
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockUpsertConfig).toHaveBeenCalledTimes(1);
    });

    expect(mockUpsertConfig).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          alert_type: "inventory_low_stock",
          channel: "fcm",
        }),
      ])
    );
  });
});

