/**
 * AC3 — Recommendations feed displays cards with Vietnamese text, confidence indicator, and actionable CTAs
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RecommendationsPage } from "@/components/RecommendationsPage";
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
  usePathname: () => "/recommendations",
}));

const mockList = api.recommendations.list as jest.MockedFunction<typeof api.recommendations.list>;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("access_token", "test-token");
  localStorage.setItem("active_shop_id", "shop-1");
});

describe("AC3: Recommendation cards with CTA", () => {
  it("renders Vietnamese message, confidence, and CTA button", async () => {
    mockList.mockResolvedValue({
      items: [
        {
          id: "rec-1",
          recommendation_type: "product_push",
          message: "Đẩy SKU A trong 30 phút đầu livestream để chốt đơn nhanh.",
          cta: "Ghim SKU A + ưu đãi 10%",
          payload: { composite_score: 0.82 },
        },
      ],
    });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("recommendations-list")).toBeInTheDocument();
    });

    expect(screen.getByText("Đẩy SKU A trong 30 phút đầu livestream để chốt đơn nhanh.")).toBeInTheDocument();
    expect(screen.getByLabelText("Độ tin cậy")).toHaveTextContent("82%");

    const ctaBtn = screen.getByTestId("recommendation-cta");
    expect(ctaBtn).toHaveTextContent("Ghim SKU A + ưu đãi 10%");

    await user.click(ctaBtn);
    expect(screen.getByRole("status")).toHaveTextContent("Đã lưu CTA");
  });
});

