import { render, screen, waitFor } from "@testing-library/react";
import { ProductsPage } from "@/components/ProductsPage";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: {
    products: {
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
  usePathname: () => "/products",
}));

const mockProducts = [
  {
    id: "p1",
    name: "Áo thun nam",
    sku: "SKU-001",
    revenue: 25_000_000,
    units_sold: 500,
    velocity: 12.5,
    velocity_trend: "accelerating" as const,
  },
  {
    id: "p2",
    name: "Quần jean nữ",
    sku: "SKU-002",
    revenue: 18_000_000,
    units_sold: 200,
    velocity: 8.2,
    velocity_trend: "decelerating" as const,
  },
  {
    id: "p3",
    name: "Giày sneaker",
    sku: "SKU-003",
    revenue: 10_000_000,
    units_sold: 100,
    velocity: 5.0,
    velocity_trend: "stable" as const,
  },
];

describe("AC1: Products page displays revenue ranking with velocity indicators", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders products ranked by revenue descending", async () => {
    (api.products.list as jest.Mock).mockResolvedValue({
      products: mockProducts,
      total: 3,
    });

    render(<ProductsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("products-list")).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId("product-card");
    expect(cards).toHaveLength(3);

    expect(cards[0]).toHaveTextContent("Áo thun nam");
    expect(cards[1]).toHaveTextContent("Quần jean nữ");
    expect(cards[2]).toHaveTextContent("Giày sneaker");
  });

  it("displays revenue amounts formatted as VND", async () => {
    (api.products.list as jest.Mock).mockResolvedValue({
      products: mockProducts,
      total: 3,
    });

    render(<ProductsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("products-list")).toBeInTheDocument();
    });

    expect(screen.getByText(/25\.000\.000/)).toBeInTheDocument();
    expect(screen.getByText(/18\.000\.000/)).toBeInTheDocument();
  });

  it("shows acceleration arrow for accelerating velocity", async () => {
    (api.products.list as jest.Mock).mockResolvedValue({
      products: mockProducts,
      total: 3,
    });

    render(<ProductsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("products-list")).toBeInTheDocument();
    });

    const acceleratingIndicator = screen.getByTestId("velocity-accelerating");
    expect(acceleratingIndicator).toBeInTheDocument();
  });

  it("shows deceleration arrow for decelerating velocity", async () => {
    (api.products.list as jest.Mock).mockResolvedValue({
      products: mockProducts,
      total: 3,
    });

    render(<ProductsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("products-list")).toBeInTheDocument();
    });

    const deceleratingIndicator = screen.getByTestId("velocity-decelerating");
    expect(deceleratingIndicator).toBeInTheDocument();
  });

  it("renders empty state when no products", async () => {
    (api.products.list as jest.Mock).mockResolvedValue({
      products: [],
      total: 0,
    });

    render(<ProductsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("products-empty")).toBeInTheDocument();
    });
  });
});
