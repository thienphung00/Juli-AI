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
  ai_recommendation: HomeAiRecommendation;
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
  alerts: [
    {
      id: "alert-001",
      type: "inventory_risk",
      severity: "high",
      title: "Tồn kho sắp hết",
      body: "Son dưỡng môi Laneige còn 12 units. Dự kiến hết hàng sau 3 ngày.",
      action_label: "Xem",
      action_href: "/operation?section=inventory",
    },
  ],
  ai_recommendation: {
    id: "rec-001",
    type: "creator_push",
    headline:
      "Creator Linh Nhi (+42% chuyển đổi với đồ dưỡng da) sẵn sàng tối nay",
    primary_action: {
      label: "Nhắn tin ngay",
      href: "/operation?section=creators&id=creator-linh-nhi",
    },
    secondary_action: { label: "Bỏ qua" },
    confidence: 0.87,
  },
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
  kpis: {
    commission_today_vnd: 12_800_000,
    commission_wow_pct: 31,
    livestream_sessions_today: 1,
    livestream_gmv_vnd: 8_400_000,
    livestream_conversion_rate: 0.072,
  },
  ai_recommendation: {
    id: "rec-aff-001",
    type: "product_opportunity",
    headline: "Son Romand #Berry đang bùng nổ — Hoa hồng 12% · Chuyển đổi 9.1%",
    primary_action: {
      label: "Đăng ký ngay",
      href: "/trends?tab=product&q=romand+berry",
    },
    secondary_action: { label: "Xem chi tiết" },
    confidence: 0.91,
  },
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
