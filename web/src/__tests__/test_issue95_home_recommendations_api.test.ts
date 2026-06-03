/**
 * Issue #95 — AC4: home hero wired to GET /v1/recommendations (not mocks)
 */
import { getHomeDashboard } from "@/lib/services/home";
import { api } from "@/lib/api-client";

jest.mock("@/lib/ui-only", () => ({
  isUiOnly: false,
  UI_ONLY_DEMO_SHOP: { id: "demo-shop" },
}));

jest.mock("@/lib/api-client", () => ({
  api: {
    shops: { list: jest.fn() },
    recommendations: { list: jest.fn() },
  },
}));

const mockShopsList = api.shops.list as jest.MockedFunction<typeof api.shops.list>;
const mockRecsList = api.recommendations.list as jest.MockedFunction<
  typeof api.recommendations.list
>;

function hostItem(id: string, score: number) {
  return {
    id,
    recommendation_type: "host_product_match",
    message: `Match ${id}`,
    cta: "Nhắn creator",
    match_score: score,
    action_type: "contact_creator",
    payload: {
      creator_name: `@creator-${id}`,
      product_name: `Product ${id}`,
    },
    predicted_outcome: {
      gmv_vnd_week: { low: 1_000_000, high: 2_000_000 },
      conversion_pct: 0.08,
      engagement_index: 0.7,
      risk_factors: [],
    },
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockShopsList.mockResolvedValue([
    { id: "shop-1", name: "BeautyShop VN", tiktok_shop_id: "7123456789" },
  ]);
});

describe("Issue #95: home recommendations API", () => {
  it("AC4: hero shows top 1–3 host_product_match rows from recommendations API", async () => {
    mockRecsList.mockResolvedValue({
      items: [
        hostItem("rec-1", 0.9),
        hostItem("rec-2", 0.85),
        hostItem("rec-3", 0.8),
        hostItem("rec-4", 0.75),
        {
          id: "push-1",
          recommendation_type: "product_push",
          message: "Legacy push",
          cta: "Pin SKU",
        },
      ],
    });

    const dashboard = await getHomeDashboard("seller");

    expect(mockRecsList).toHaveBeenCalled();
    expect(dashboard.mode).toBe("seller");
    expect(dashboard.hero_matches).toHaveLength(3);
    expect(dashboard.hero_matches.map((m) => m.id)).toEqual(["rec-1", "rec-2", "rec-3"]);
    expect(dashboard.hero_matches[0].creator_name).toBe("@creator-rec-1");
    expect(dashboard.ai_recommendation.headline).toContain("Match rec-1");
  });

  it("AC4: sparse API leaves hero empty and collecting-data headline", async () => {
    mockRecsList.mockResolvedValue({
      items: [
        {
          id: "push-1",
          recommendation_type: "product_push",
          message: "Push only",
          cta: "Pin",
        },
      ],
    });

    const dashboard = await getHomeDashboard("seller");

    expect(dashboard.hero_matches).toHaveLength(0);
    expect(dashboard.ai_recommendation.headline).toContain("Đang thu thập dữ liệu");
  });
});
