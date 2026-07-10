import { getMockWorkspaceAlerts, toHomeAlertCards } from "@/lib/mock-data/alerts";
import type { WorkspaceMode } from "@/lib/workspace-mode";

export interface HomeAlertCard {
  id: string;
  type: string;
  severity: "high" | "medium" | "low" | "info";
  title: string;
  body: string;
  action_label?: string;
  action_href?: string;
}

export interface HomeActionLink {
  label: string;
  href: string;
}

export interface HomeAiRecommendation {
  id: string;
  type: string;
  headline: string;
  primary_action: HomeActionLink;
  secondary_action?: { label: string; href?: string };
  confidence: number;
}

/** Top match summaries for home hero (issue #95). */
export interface HomeHeroMatch {
  id: string;
  type: string;
  headline: string;
  cta: string;
  match_score: number;
  creator_name: string;
  product_name: string;
  action_type: string;
  primary_action_href: string;
}

export interface SellerHomeKpis {
  gmv_today_vnd: number;
  gmv_wow_pct: number;
  active_livestreams: number;
  active_livestream_viewers: number;
}

export interface AffiliateHomeKpis {
  commission_today_vnd: number;
  commission_wow_pct: number;
  livestream_sessions_today: number;
  livestream_gmv_vnd: number;
  livestream_conversion_rate: number;
}

export interface SellerHomeDashboard {
  mode: "seller";
  shop: { name: string; tiktok_shop_id: string };
  kpis: SellerHomeKpis;
  alerts: HomeAlertCard[];
  ai_recommendation: HomeAiRecommendation;
  hero_matches: HomeHeroMatch[];
  top_creator: {
    id: string;
    handle: string;
    gmv_today_vnd: number;
    conversion_rate: number;
    conversion_delta: number;
  };
  top_product: {
    id: string;
    name: string;
    orders_today: number;
    gmv_today_vnd: number;
    ctr: number;
  };
}

export interface AffiliateHomeDashboard {
  mode: "affiliate";
  creator: { handle: string; follower_count: number };
  kpis: AffiliateHomeKpis;
  alerts: HomeAlertCard[];
  ai_recommendation: HomeAiRecommendation;
  hero_matches: HomeHeroMatch[];
  audience_fit_products: Array<{
    id: string;
    name: string;
    fit_score: number;
    commission_pct: number;
  }>;
  content_performance: {
    video_yesterday_views: number;
    product_click_rate: number;
  };
}

export type HomeDashboardData = SellerHomeDashboard | AffiliateHomeDashboard;

export const MOCK_HOME_SELLER: SellerHomeDashboard = {
  mode: "seller",
  shop: { name: "BeautyShop VN", tiktok_shop_id: "7123456789" },
  kpis: {
    gmv_today_vnd: 84_200_000,
    gmv_wow_pct: 18,
    active_livestreams: 2,
    active_livestream_viewers: 1240,
  },
  alerts: toHomeAlertCards(getMockWorkspaceAlerts("seller")),
  ai_recommendation: {
    id: "rec-001",
    type: "host_product_match",
    headline:
      "Tăng hoa hồng 5% dự kiến +18% GMV/tuần với @linh.nhi × Son Laneige Berry",
    primary_action: {
      label: "Nhắn creator ngay",
      href: "/recommendations",
    },
    confidence: 0.87,
  },
  hero_matches: [
    {
      id: "rec-001",
      type: "host_product_match",
      headline:
        "Tăng hoa hồng 5% dự kiến +18% GMV/tuần với @linh.nhi × Son Laneige Berry",
      cta: "Nhắn creator ngay",
      match_score: 0.87,
      creator_name: "@linh.nhi",
      product_name: "Son Laneige Berry",
      action_type: "contact_creator",
      primary_action_href: "/recommendations",
    },
    {
      id: "rec-002",
      type: "host_product_match",
      headline: "Ghép @beauty.min với serum Vitamin C — chuyển đổi +12%",
      cta: "Điều chỉnh hoa hồng",
      match_score: 0.79,
      creator_name: "@beauty.min",
      product_name: "Serum Vitamin C",
      action_type: "adjust_commission",
      primary_action_href: "/recommendations",
    },
  ],
  top_creator: {
    id: "creator-linh-nhi",
    handle: "@linh.nhi.beauty",
    gmv_today_vnd: 23_400_000,
    conversion_rate: 0.083,
    conversion_delta: 0.021,
  },
  top_product: {
    id: "prod-laneige-berry-3",
    name: "Son dưỡng môi Laneige #3 Berry",
    orders_today: 312,
    gmv_today_vnd: 31_200_000,
    ctr: 0.092,
  },
};

export const MOCK_HOME_AFFILIATE: AffiliateHomeDashboard = {
  mode: "affiliate",
  creator: { handle: "@linh.nhi.beauty", follower_count: 284_000 },
  alerts: toHomeAlertCards(getMockWorkspaceAlerts("affiliate")),
  kpis: {
    commission_today_vnd: 12_800_000,
    commission_wow_pct: 31,
    livestream_sessions_today: 1,
    livestream_gmv_vnd: 8_400_000,
    livestream_conversion_rate: 0.072,
  },
  ai_recommendation: {
    id: "rec-aff-001",
    type: "host_product_match",
    headline: "Son Romand #Berry — Hoa hồng 12% · Chuyển đổi 9.1%",
    primary_action: {
      label: "Xem gợi ý",
      href: "/recommendations",
    },
    confidence: 0.91,
  },
  hero_matches: [
    {
      id: "rec-aff-001",
      type: "host_product_match",
      headline: "Son Romand #Berry — Hoa hồng 12% · Chuyển đổi 9.1%",
      cta: "Xem gợi ý",
      match_score: 0.91,
      creator_name: "@linh.nhi.beauty",
      product_name: "Son Romand Berry",
      action_type: "schedule_live",
      primary_action_href: "/recommendations",
    },
  ],
  audience_fit_products: [
    {
      id: "prod-laneige-berry",
      name: "Son Laneige Berry",
      fit_score: 0.94,
      commission_pct: 10,
    },
    {
      id: "prod-3ce-velvet",
      name: "Son 3CE Velvet",
      fit_score: 0.88,
      commission_pct: 8,
    },
    {
      id: "prod-mac-ruby",
      name: "MAC Ruby Woo",
      fit_score: 0.81,
      commission_pct: 9,
    },
  ],
  content_performance: {
    video_yesterday_views: 48_000,
    product_click_rate: 0.068,
  },
};

export function getMockHomeDashboard(mode: WorkspaceMode): HomeDashboardData {
  return mode === "seller" ? MOCK_HOME_SELLER : MOCK_HOME_AFFILIATE;
}
