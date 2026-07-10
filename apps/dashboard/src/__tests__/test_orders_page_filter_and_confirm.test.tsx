/**
 * AC4 — Orders page with status filtering, date range picker,
 * and one-tap shipment confirmation
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OrdersPage } from "@/components/OrdersPage";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: { sendOtp: jest.fn(), verifyOtp: jest.fn() },
    shops: { list: jest.fn(), me: jest.fn() },
    orders: {
      list: jest.fn(),
      confirmShipment: jest.fn(),
    },
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
  usePathname: () => "/orders",
}));

const mockOrdersList = api.orders.list as jest.MockedFunction<typeof api.orders.list>;
const mockConfirmShipment = api.orders.confirmShipment as jest.MockedFunction<
  typeof api.orders.confirmShipment
>;

const sampleOrders = [
  {
    id: "ord-1",
    order_id: "TK001",
    status: "AWAITING_SHIPMENT",
    total_amount: 250000,
    currency: "VND",
    created_at: "2024-06-15T10:00:00Z",
    updated_at: "2024-06-15T10:00:00Z",
    buyer_name: "Nguyễn Văn A",
    items_count: 3,
  },
  {
    id: "ord-2",
    order_id: "TK002",
    status: "DELIVERED",
    total_amount: 500000,
    currency: "VND",
    created_at: "2024-06-14T08:00:00Z",
    updated_at: "2024-06-15T09:00:00Z",
    buyer_name: "Trần Thị B",
    items_count: 1,
  },
];

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("access_token", "test-token");
  localStorage.setItem("active_shop_id", "shop-1");
});

describe("AC4: Orders page filtering and shipment confirmation", () => {
  it("renders order list with data", async () => {
    mockOrdersList.mockResolvedValue({
      orders: sampleOrders,
      total: 2,
      page: 1,
      page_size: 20,
    });

    render(<OrdersPage />);

    await waitFor(() => {
      expect(screen.getByTestId("orders-list")).toBeInTheDocument();
    });

    expect(screen.getByText("#TK001")).toBeInTheDocument();
    expect(screen.getByText("#TK002")).toBeInTheDocument();
    expect(screen.getByText("2 đơn hàng")).toBeInTheDocument();
  });

  it("shows empty state when no orders", async () => {
    mockOrdersList.mockResolvedValue({
      orders: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    render(<OrdersPage />);

    await waitFor(() => {
      expect(screen.getByTestId("orders-empty")).toBeInTheDocument();
    });

    expect(screen.getByText("Chưa có đơn hàng nào")).toBeInTheDocument();
  });

  it("has status filter dropdown with Vietnamese labels", async () => {
    mockOrdersList.mockResolvedValue({
      orders: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    render(<OrdersPage />);

    const select = screen.getByLabelText("Lọc theo trạng thái");
    expect(select).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Tất cả")).toBeInTheDocument();
    });
  });

  it("filters orders by status", async () => {
    mockOrdersList.mockResolvedValue({
      orders: sampleOrders,
      total: 2,
      page: 1,
      page_size: 20,
    });

    const user = userEvent.setup();
    render(<OrdersPage />);

    await waitFor(() => {
      expect(screen.getByTestId("orders-list")).toBeInTheDocument();
    });

    mockOrdersList.mockResolvedValue({
      orders: [sampleOrders[0]],
      total: 1,
      page: 1,
      page_size: 20,
    });

    const select = screen.getByLabelText("Lọc theo trạng thái");
    await user.selectOptions(select, "AWAITING_SHIPMENT");

    await waitFor(() => {
      expect(mockOrdersList).toHaveBeenCalledWith(
        expect.objectContaining({ status: "AWAITING_SHIPMENT" })
      );
    });
  });

  it("has date range inputs", async () => {
    mockOrdersList.mockResolvedValue({
      orders: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    render(<OrdersPage />);

    expect(screen.getByLabelText("Từ ngày")).toBeInTheDocument();
    expect(screen.getByLabelText("Đến ngày")).toBeInTheDocument();
  });

  it("shows shipment confirmation button only for AWAITING_SHIPMENT orders", async () => {
    mockOrdersList.mockResolvedValue({
      orders: sampleOrders,
      total: 2,
      page: 1,
      page_size: 20,
    });

    render(<OrdersPage />);

    await waitFor(() => {
      expect(screen.getByTestId("orders-list")).toBeInTheDocument();
    });

    const confirmBtns = screen.getAllByTestId("confirm-shipment-btn");
    expect(confirmBtns).toHaveLength(1);
    expect(confirmBtns[0]).toHaveTextContent("Xác nhận giao hàng");
  });

  it("confirms shipment on one-tap and reloads", async () => {
    mockOrdersList.mockResolvedValue({
      orders: sampleOrders,
      total: 2,
      page: 1,
      page_size: 20,
    });
    mockConfirmShipment.mockResolvedValue({ success: true });

    const user = userEvent.setup();
    render(<OrdersPage />);

    await waitFor(() => {
      expect(screen.getByTestId("orders-list")).toBeInTheDocument();
    });

    const confirmBtn = screen.getByTestId("confirm-shipment-btn");
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(mockConfirmShipment).toHaveBeenCalledWith("ord-1");
    });

    // Should reload orders after confirmation
    expect(mockOrdersList).toHaveBeenCalledTimes(2);
  });

  it("displays VND formatted amounts", async () => {
    mockOrdersList.mockResolvedValue({
      orders: sampleOrders,
      total: 2,
      page: 1,
      page_size: 20,
    });

    render(<OrdersPage />);

    await waitFor(() => {
      expect(screen.getByText("250.000 ₫")).toBeInTheDocument();
    });
  });
});
