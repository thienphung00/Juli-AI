import { render, screen, waitFor } from "@testing-library/react";
import { InventoryPage } from "@/components/InventoryPage";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: {
    inventory: {
      list: jest.fn(),
    },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

jest.mock("next/navigation", () => ({
  usePathname: () => "/inventory",
}));

const mockInventory = [
  {
    id: "inv1",
    product_name: "Áo thun nam",
    sku: "SKU-001",
    current_stock: 45,
    daily_velocity: 15,
    days_until_depletion: 3,
    reorder_recommended: true,
    reorder_quantity: 200,
  },
  {
    id: "inv2",
    product_name: "Quần jean nữ",
    sku: "SKU-002",
    current_stock: 500,
    daily_velocity: 5,
    days_until_depletion: 100,
    reorder_recommended: false,
    reorder_quantity: 0,
  },
  {
    id: "inv3",
    product_name: "Giày sneaker",
    sku: "SKU-003",
    current_stock: 20,
    daily_velocity: 10,
    days_until_depletion: 2,
    reorder_recommended: true,
    reorder_quantity: 150,
  },
];

describe("AC2: Inventory page shows depletion forecast and reorder recommendations", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("displays depletion forecast (days until depletion) per SKU", async () => {
    (api.inventory.list as jest.Mock).mockResolvedValue({
      items: mockInventory,
      total: 3,
    });

    render(<InventoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId("inventory-list")).toBeInTheDocument();
    });

    expect(screen.getByText(/3 ngày/)).toBeInTheDocument();
    expect(screen.getByText(/100 ngày/)).toBeInTheDocument();
    expect(screen.getByText(/2 ngày/)).toBeInTheDocument();
  });

  it("shows reorder recommendation badge for items needing restock", async () => {
    (api.inventory.list as jest.Mock).mockResolvedValue({
      items: mockInventory,
      total: 3,
    });

    render(<InventoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId("inventory-list")).toBeInTheDocument();
    });

    const reorderBadges = screen.getAllByTestId("reorder-badge");
    expect(reorderBadges).toHaveLength(2);
  });

  it("displays recommended reorder quantity", async () => {
    (api.inventory.list as jest.Mock).mockResolvedValue({
      items: mockInventory,
      total: 3,
    });

    render(<InventoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId("inventory-list")).toBeInTheDocument();
    });

    expect(screen.getByText(/200/)).toBeInTheDocument();
    expect(screen.getByText(/150/)).toBeInTheDocument();
  });

  it("shows current stock level per item", async () => {
    (api.inventory.list as jest.Mock).mockResolvedValue({
      items: mockInventory,
      total: 3,
    });

    render(<InventoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId("inventory-list")).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId("inventory-card");
    expect(cards).toHaveLength(3);
    expect(cards[0]).toHaveTextContent("45");
    expect(cards[1]).toHaveTextContent("500");
  });

  it("renders empty state when no inventory data", async () => {
    (api.inventory.list as jest.Mock).mockResolvedValue({
      items: [],
      total: 0,
    });

    render(<InventoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId("inventory-empty")).toBeInTheDocument();
    });
  });

  it("highlights critical items (<=7 days until depletion) with warning style", async () => {
    (api.inventory.list as jest.Mock).mockResolvedValue({
      items: mockInventory,
      total: 3,
    });

    render(<InventoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId("inventory-list")).toBeInTheDocument();
    });

    const criticalItems = screen.getAllByTestId("depletion-critical");
    expect(criticalItems.length).toBeGreaterThanOrEqual(2);
  });
});
