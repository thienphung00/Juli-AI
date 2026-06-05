/**
 * Issue #95 — Recommendation-first nav (AC1, AC5)
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NavBar } from "@/components/NavBar";
import { AuthProvider } from "@/lib/auth-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  BOTTOM_NAV_TABS,
  LEGACY_ROUTE_REDIRECTS,
} from "@/lib/nav-config";
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

const mockList = api.recommendations.list as jest.MockedFunction<
  typeof api.recommendations.list
>;

const mockPathname = jest.fn(() => "/recommendations");

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => mockPathname(),
}));

function renderNav() {
  return render(
    <AuthProvider>
      <ModeProvider>
        <NavBar />
      </ModeProvider>
    </AuthProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("access_token", "test-token");
  localStorage.setItem("active_shop_id", "shop-1");
  mockPathname.mockReturnValue("/recommendations");
});

describe("Issue #95: recommendation-first nav (component tests retained)", () => {
  it("legacy creator-matching routes are registered for 301 redirect to seller home (#123)", () => {
    const redirectedSources = LEGACY_ROUTE_REDIRECTS.map((r) => r.source);
    expect(redirectedSources).toContain("/creators");
    expect(redirectedSources).toContain("/recommendations");
  });

  it("primary nav no longer links to /creators or /recommendations (#123)", () => {
    expect(BOTTOM_NAV_TABS.map((t) => t.href)).not.toContain("/creators");
    expect(BOTTOM_NAV_TABS.map((t) => t.href)).not.toContain("/recommendations");

    renderNav();
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(nav.querySelector('a[href="/creators"]')).not.toBeInTheDocument();
    expect(nav.querySelector('a[href="/recommendations"]')).not.toBeInTheDocument();
  });

  it("AC5: CTA tap dispatches juli:analytics recommendation_action_tapped", async () => {
    const analyticsEvents: CustomEvent[] = [];
    const onAnalytics = (event: Event) => {
      analyticsEvents.push(event as CustomEvent);
    };
    window.addEventListener("juli:analytics", onAnalytics);

    mockList.mockResolvedValue({
      items: [
        {
          id: "rec-host-1",
          recommendation_type: "host_product_match",
          message: "Tăng hoa hồng 5% dự kiến +18% GMV/tuần với @linh.nhi",
          cta: "Nhắn creator ngay",
          match_score: 0.87,
          action_type: "contact_creator",
          confidence: "high",
          payload: {
            creator_id: "c-1",
            creator_name: "@linh.nhi",
            product_name: "Son Laneige Berry",
            tiktok_product_id: "p-1",
          },
          predicted_outcome: {
            gmv_vnd_week: { low: 12_000_000, high: 18_000_000 },
            conversion_pct: 0.083,
            engagement_index: 0.72,
            risk_factors: ["Tồn kho thấp"],
          },
        },
      ],
    });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await screen.findByTestId("match-decision-card");
    await user.click(screen.getByTestId("recommendation-cta"));

    const tapped = analyticsEvents.filter(
      (e) => e.detail?.event === "recommendation_action_tapped"
    );
    expect(tapped).toHaveLength(1);
    expect(tapped[0].detail).toEqual(
      expect.objectContaining({
        event: "recommendation_action_tapped",
        recommendationId: "rec-host-1",
        recommendationType: "host_product_match",
        actionType: "contact_creator",
        creatorId: "c-1",
        productId: "p-1",
        matchScore: 0.87,
      })
    );

    window.removeEventListener("juli:analytics", onAnalytics);
  });
});
