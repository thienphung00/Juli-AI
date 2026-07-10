import { api, type RecommendationItem } from "@/lib/api-client";
import {
  getMockHomeDashboard,
  type AffiliateHomeDashboard,
  type HomeDashboardData,
  type HomeAiRecommendation,
  type HomeHeroMatch,
  type SellerHomeDashboard,
} from "@/lib/mock-data/home";
import {
  creatorNameFromItem,
  matchScorePercent,
  productNameFromItem,
} from "@/lib/recommendation-utils";
import { isUiOnly, UI_ONLY_DEMO_SHOP } from "@/lib/ui-only";
import type { WorkspaceMode } from "@/lib/workspace-mode";

function mapRecommendation(item: RecommendationItem): HomeAiRecommendation {
  const score = matchScorePercent(item);
  const confidence = score !== null ? score / 100 : 0.5;

  return {
    id: item.id,
    type: item.recommendation_type,
    headline: item.message,
    primary_action: { label: item.cta, href: "/recommendations" },
    confidence,
  };
}

function mapHeroMatch(item: RecommendationItem): HomeHeroMatch {
  const score = matchScorePercent(item);
  return {
    id: item.id,
    type: item.recommendation_type,
    headline: item.message,
    cta: item.cta,
    match_score: score !== null ? score / 100 : 0.5,
    creator_name: creatorNameFromItem(item),
    product_name: productNameFromItem(item),
    action_type: item.action_type ?? "contact_creator",
    primary_action_href: "/recommendations",
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
      headline: "Đang thu thập dữ liệu — chưa có ghép creator",
      primary_action: { label: "Xem gợi ý", href: "/recommendations" },
      confidence: 0,
    },
    hero_matches: [],
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
    alerts: [],
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
      headline: "Đang thu thập dữ liệu — chưa có cơ hội ghép",
      primary_action: { label: "Xem gợi ý", href: "/recommendations" },
      confidence: 0,
    },
    hero_matches: [],
    audience_fit_products: [],
    content_performance: {
      video_yesterday_views: 0,
      product_click_rate: 0,
    },
  };
}

function applyRecommendationsToDashboard(
  base: SellerHomeDashboard | AffiliateHomeDashboard,
  items: RecommendationItem[]
): void {
  const hostMatches = items.filter(
    (item) => item.recommendation_type === "host_product_match"
  );
  const ranked = hostMatches.slice(0, 3);

  base.hero_matches = ranked.map(mapHeroMatch);

  const topRec = ranked[0];
  if (topRec) {
    base.ai_recommendation = mapRecommendation(topRec);
  }
}

export async function getHomeDashboard(mode: WorkspaceMode): Promise<HomeDashboardData> {
  if (isUiOnly) {
    return getMockHomeDashboard(mode);
  }

  const shops = await api.shops.list();
  const shop = shops[0];
  const shopName = shop?.name ?? "Cửa hàng";

  const recs = await api.recommendations
    .list()
    .catch(() => ({ items: [] as RecommendationItem[] }));

  if (mode === "seller") {
    const base = emptySellerDashboard(shopName);
    if (shop) {
      base.shop.tiktok_shop_id = shop.tiktok_shop_id;
    }
    applyRecommendationsToDashboard(base, recs.items ?? []);
    return base;
  }

  const base = emptyAffiliateDashboard(shopName);
  applyRecommendationsToDashboard(base, recs.items ?? []);
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
