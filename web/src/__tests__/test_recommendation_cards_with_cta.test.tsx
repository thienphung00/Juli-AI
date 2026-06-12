/**
 * Issue #95 — Recommendations feed: match cards, empty state, CTAs
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

describe("Issue #95: Recommendation feed", () => {
  it("AC3: empty state shows collecting-data copy", async () => {
    mockList.mockResolvedValue({ items: [] });
    render(<RecommendationsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("recommendations-empty")).toBeInTheDocument();
    });
    expect(screen.getByText("Đang thu thập dữ liệu")).toBeInTheDocument();
  });

  it("AC3: sparse API (product_push only) shows collecting-data copy", async () => {
    mockList.mockResolvedValue({
      items: [
        {
          id: "rec-push",
          recommendation_type: "product_push",
          message: "Đẩy SKU trong livestream",
          cta: "Ghim SKU",
          payload: { composite_score: 0.75 },
        },
      ],
    });
    render(<RecommendationsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("recommendations-empty")).toBeInTheDocument();
    });
    expect(screen.getByText("Đang thu thập dữ liệu")).toBeInTheDocument();
    expect(screen.queryByTestId("match-decision-card")).not.toBeInTheDocument();
  });

  it("AC2: host_product_match renders match score, predicted block, and CTA", async () => {
    mockList.mockResolvedValue({
      items: [
        {
          id: "rec-1",
          recommendation_type: "host_product_match",
          message: "Tăng hoa hồng 5% dự kiến +18% GMV/tuần",
          cta: "Nhắn creator ngay",
          match_score: 0.82,
          action_type: "contact_creator",
          payload: {
            creator_name: "@linh.nhi",
            product_name: "Son Laneige",
          },
          predicted_outcome: {
            gmv_vnd_week: { low: 10_000_000, high: 15_000_000 },
            conversion_pct: 0.08,
            engagement_index: 0.7,
            risk_factors: ["Tồn kho thấp"],
          },
        },
      ],
    });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("match-decision-card")).toBeInTheDocument();
    });

    expect(screen.getByLabelText("Điểm ghép")).toHaveTextContent("82%");
    expect(screen.getByTestId("predicted-outcome-panel")).toBeInTheDocument();
    expect(screen.getByText("Tăng hoa hồng 5% dự kiến +18% GMV/tuần")).toBeInTheDocument();

    const ctaBtn = screen.getByTestId("recommendation-cta");
    await user.click(ctaBtn);
    expect(screen.getByRole("status")).toHaveTextContent("Đã lưu CTA");
  });

  it("renders legacy product_push alongside host_product_match when graph is not sparse", async () => {
    mockList.mockResolvedValue({
      items: [
        {
          id: "rec-host",
          recommendation_type: "host_product_match",
          message: "Ghép creator",
          cta: "Nhắn creator",
          match_score: 0.8,
          payload: { creator_name: "@a", product_name: "SKU" },
        },
        {
          id: "rec-push",
          recommendation_type: "product_push",
          message: "Đẩy SKU A trong 30 phút đầu livestream để chốt đơn nhanh.",
          cta: "Ghim SKU A + ưu đãi 10%",
          payload: { composite_score: 0.82 },
        },
      ],
    });

    render(<RecommendationsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("match-decision-card")).toBeInTheDocument();
      expect(screen.getByTestId("recommendation-card")).toBeInTheDocument();
    });
    expect(screen.queryByLabelText("Độ tin cậy")).not.toBeInTheDocument();
  });
});

