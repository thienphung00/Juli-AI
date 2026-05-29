import { api, type RecommendationItem } from "@/lib/api-client";
import {
  getMockHomeDashboard,
  type AffiliateHomeDashboard,
  type HomeDashboardData,
  type HomeAiRecommendation,
  type SellerHomeDashboard,
} from "@/lib/mock-data/home";
import { isUiOnly, UI_ONLY_DEMO_SHOP } from "@/lib/ui-only";
import type { WorkspaceMode } from "@/lib/workspace-mode";

function mapRecommendation(item: RecommendationItem): HomeAiRecommendation {
  const payload = item.payload ?? {};
  const rawConfidence =
    typeof payload["composite_score"] === "number"
      ? payload["composite_score"]
      : typeof payload["match_score"] === "number"
        ? payload["match_score"]
        : 0.5;

  const confidence = rawConfidence > 1 ? rawConfidence / 100 : rawConfidence;

  return {
    id: item.id,
    type: item.recommendation_type,
    headline: item.message,
    primary_action: { label: item.cta, href: "/operation" },
    confidence,
  };
}

function emptySellerDashboard(shopName: string): SellerHomeDashboard {
  return {
    mode: "seller",
    shop: { name: shopName, tiktok_shop_id: "" },
    kpis: {
      gmv_today_vnd: 0,
      gmv_wow_pct: 0,
      active_livestreams: 0,
      active_livestream_viewers: 0,
    },
    alerts: [],
    ai_recommendation: {
      id: "empty",
      type: "none",
      headline: "Chưa có gợi ý — dữ liệu đang được thu thập",
      primary_action: { label: "Xem xu hướng", href: "/trends" },
      confidence: 0,
    },
    top_creator: {
      id: "empty",
      handle: "—",
      gmv_today_vnd: 0,
      conversion_rate: 0,
      conversion_delta: 0,
    },
    top_product: {
      id: "empty",
      name: "Chưa có dữ liệu",
      orders_today: 0,
      gmv_today_vnd: 0,
      ctr: 0,
    },
  };
}

function emptyAffiliateDashboard(handle: string): AffiliateHomeDashboard {
  return {
    mode: "affiliate",
    creator: { handle, follower_count: 0 },
    kpis: {
      commission_today_vnd: 0,
      commission_wow_pct: 0,
      livestream_sessions_today: 0,
      livestream_gmv_vnd: 0,
      livestream_conversion_rate: 0,
    },
    ai_recommendation: {
      id: "empty",
      type: "none",
      headline: "Chưa có cơ hội hoa hồng — dữ liệu đang được thu thập",
      primary_action: { label: "Khám phá xu hướng", href: "/trends" },
      confidence: 0,
    },
    audience_fit_products: [],
    content_performance: {
      video_yesterday_views: 0,
      product_click_rate: 0,
    },
  };
}

export async function getHomeDashboard(mode: WorkspaceMode): Promise<HomeDashboardData> {
  if (isUiOnly) {
    return getMockHomeDashboard(mode);
  }

  const shops = await api.shops.list();
  const shop = shops[0];
  const shopName = shop?.name ?? "Cửa hàng";

  if (mode === "seller") {
    const [recs, alerts] = await Promise.all([
      api.recommendations.list().catch(() => ({ items: [] as RecommendationItem[] })),
      api.alerts.history({ limit: 5 }).catch(() => ({ items: [] })),
    ]);

    const base = emptySellerDashboard(shopName);
    if (shop) {
      base.shop.tiktok_shop_id = shop.tiktok_shop_id;
    }

    const topRec = recs.items?.[0];
    if (topRec) {
      base.ai_recommendation = mapRecommendation(topRec);
    }

    base.alerts = (alerts.items ?? []).slice(0, 3).map((item) => ({
      id: item.id,
      type: item.alert_type,
      severity: "info" as const,
      title: item.alert_type,
      body:
        typeof item.payload?.message === "string"
          ? item.payload.message
          : item.alert_type,
    }));

    return base;
  }

  const base = emptyAffiliateDashboard(shopName);
  const recs = await api.recommendations
    .list()
    .catch(() => ({ items: [] as RecommendationItem[] }));
  const topRec = recs.items?.[0];
  if (topRec) {
    base.ai_recommendation = mapRecommendation(topRec);
  }

  return base;
}

export function getHomeSubtitle(data: HomeDashboardData): string {
  if (data.mode === "seller") {
    return data.shop.name;
  }
  return data.creator.handle;
}

export async function resolveHomeShopId(): Promise<string | null> {
  if (isUiOnly) {
    return UI_ONLY_DEMO_SHOP.id;
  }

  const shops = await api.shops.list();
  if (shops.length === 0) return null;
  localStorage.setItem("active_shop_id", shops[0].id);
  return shops[0].id;
}
