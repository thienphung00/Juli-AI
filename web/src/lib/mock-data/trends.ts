import type { WorkspaceMode } from "@/lib/workspace-mode";

export type TrendsTab = "product" | "creator" | "shop";

export interface TrendsProduct {
  id: string;
  rank: number;
  name: string;
  price_vnd: number;
  growth_7d_pct: number;
  commission_pct: number;
  seller_creator_fit_score: number;
}

export interface TrendsCreatorSeller {
  id: string;
  rank: number;
  handle: string;
  followers: number;
  category: string;
  brand_fit_score: number;
  avg_conversion_rate: number;
  refund_rate: number;
  content_style: string;
}

export interface TrendsCreatorAffiliate {
  id: string;
  rank: number;
  handle: string;
  followers: number;
  category: string;
  gmv_growth_7d_pct: number;
  products_currently_promoting: string[];
  content_format: string;
  audience_overlap_pct: number;
}

export interface TrendsShopSeller {
  id: string;
  name: string;
  rating: number;
  followers: number;
  category: string;
  creator_network_size: number;
  commission_range_pct: string;
  top_product: string;
  commission_delta_alert: string | null;
}

export interface TrendsShopAffiliate {
  id: string;
  name: string;
  rating: number;
  followers: number;
  category: string;
  audience_fit_score: number;
  commission_range: string;
  avg_commission_pct: number;
  accepts_new_affiliates: boolean;
  sample_approval_days: number;
}

export const MOCK_TRENDS_PRODUCTS: TrendsProduct[] = [
  {
    id: "prod-romand-cherry",
    rank: 1,
    name: "Son Romand Juicy Lasting Tint #Cherry",
    price_vnd: 185_000,
    growth_7d_pct: 340,
    commission_pct: 12,
    seller_creator_fit_score: 0.94,
  },
  {
    id: "prod-anessa-spf50",
    rank: 2,
    name: "Kem chống nắng Anessa Perfect UV SPF50",
    price_vnd: 420_000,
    growth_7d_pct: 185,
    commission_pct: 8,
    seller_creator_fit_score: 0.87,
  },
  {
    id: "prod-bioderma-micellar",
    rank: 3,
    name: "Nước tẩy trang Bioderma Sensibio H2O",
    price_vnd: 295_000,
    growth_7d_pct: 127,
    commission_pct: 10,
    seller_creator_fit_score: 0.81,
  },
];

export const MOCK_TRENDS_CREATORS_SELLER: TrendsCreatorSeller[] = [
  {
    id: "creator-beauty-trending",
    rank: 1,
    handle: "@beauty.trending.vn",
    followers: 1_200_000,
    category: "Làm đẹp & skincare",
    brand_fit_score: 0.94,
    avg_conversion_rate: 0.087,
    refund_rate: 0.012,
    content_style: "Tutorial · Authentic",
  },
  {
    id: "creator-linh-nhi",
    rank: 2,
    handle: "@linh.nhi.beauty",
    followers: 284_000,
    category: "Son môi & lip care",
    brand_fit_score: 0.91,
    avg_conversion_rate: 0.083,
    refund_rate: 0.009,
    content_style: "Review · Honest",
  },
  {
    id: "creator-glow-skincare",
    rank: 3,
    handle: "@glow.skincare.vn",
    followers: 512_000,
    category: "Skincare routine",
    brand_fit_score: 0.86,
    avg_conversion_rate: 0.079,
    refund_rate: 0.014,
    content_style: "GRWM · Daily routine",
  },
];

export const MOCK_TRENDS_CREATORS_AFFILIATE: TrendsCreatorAffiliate[] = [
  {
    id: "creator-glow-vn",
    rank: 1,
    handle: "@glow.vn.beauty",
    followers: 890_000,
    category: "Skincare routine",
    gmv_growth_7d_pct: 280,
    products_currently_promoting: ["Serum", "Kem dưỡng"],
    content_format: "Tutorial-style · 2h streams",
    audience_overlap_pct: 67,
  },
  {
    id: "creator-skincare-daily",
    rank: 2,
    handle: "@skincare.dailyvn",
    followers: 430_000,
    category: "Skincare & makeup",
    gmv_growth_7d_pct: 145,
    products_currently_promoting: ["Son môi", "Tẩy trang"],
    content_format: "GRWM · 1h streams",
    audience_overlap_pct: 54,
  },
  {
    id: "creator-beauty-hanoi",
    rank: 3,
    handle: "@beauty.hanoi",
    followers: 178_000,
    category: "Skincare",
    gmv_growth_7d_pct: 92,
    products_currently_promoting: ["Kem chống nắng", "Serum"],
    content_format: "Review · 45m streams",
    audience_overlap_pct: 41,
  },
];

export const MOCK_TRENDS_SHOPS_SELLER: TrendsShopSeller[] = [
  {
    id: "shop-romand-vn",
    name: "Romand Vietnam Official",
    rating: 4.9,
    followers: 214_000,
    category: "Son môi",
    creator_network_size: 48,
    commission_range_pct: "12–15%",
    top_product: "Juicy Tint Cherry",
    commission_delta_alert: "+2% tháng này",
  },
  {
    id: "shop-anessa-vn",
    name: "Anessa Vietnam Official",
    rating: 4.8,
    followers: 94_000,
    category: "Chống nắng",
    creator_network_size: 31,
    commission_range_pct: "8–12%",
    top_product: "Anessa Perfect UV SPF50",
    commission_delta_alert: null,
  },
];

export const MOCK_TRENDS_SHOPS_AFFILIATE: TrendsShopAffiliate[] = [
  {
    id: "shop-laneige-vn",
    name: "LaneigeSkincare Official",
    rating: 4.9,
    followers: 128_000,
    category: "Lip care",
    audience_fit_score: 0.94,
    commission_range: "10–14%",
    avg_commission_pct: 12,
    accepts_new_affiliates: true,
    sample_approval_days: 3,
  },
  {
    id: "shop-bioderma-vn",
    name: "Bioderma Vietnam",
    rating: 4.7,
    followers: 67_000,
    category: "Tẩy trang",
    audience_fit_score: 0.88,
    commission_range: "9–11%",
    avg_commission_pct: 10,
    accepts_new_affiliates: true,
    sample_approval_days: 5,
  },
];

export interface TrendsResults {
  tab: TrendsTab;
  mode: WorkspaceMode;
  products: TrendsProduct[];
  creatorsSeller: TrendsCreatorSeller[];
  creatorsAffiliate: TrendsCreatorAffiliate[];
  shopsSeller: TrendsShopSeller[];
  shopsAffiliate: TrendsShopAffiliate[];
  market_intel_placeholder: boolean;
}

function normalizeQuery(q: string): string {
  return q.trim().toLowerCase();
}

function matchesQuery(text: string, query: string): boolean {
  if (!query) return true;
  return text.toLowerCase().includes(query);
}

export function filterTrendsMock(
  mode: WorkspaceMode,
  tab: TrendsTab,
  query: string
): TrendsResults {
  const q = normalizeQuery(query);

  const products = MOCK_TRENDS_PRODUCTS.filter((item) =>
    matchesQuery(item.name, q)
  );

  const creatorsSeller = MOCK_TRENDS_CREATORS_SELLER.filter(
    (item) =>
      matchesQuery(item.handle, q) ||
      matchesQuery(item.category, q)
  );

  const creatorsAffiliate = MOCK_TRENDS_CREATORS_AFFILIATE.filter(
    (item) =>
      matchesQuery(item.handle, q) ||
      matchesQuery(item.category, q) ||
      item.products_currently_promoting.some((p) => matchesQuery(p, q))
  );

  const shopsSeller = MOCK_TRENDS_SHOPS_SELLER.filter(
    (item) =>
      matchesQuery(item.name, q) ||
      matchesQuery(item.category, q) ||
      matchesQuery(item.top_product, q)
  );

  const shopsAffiliate = MOCK_TRENDS_SHOPS_AFFILIATE.filter(
    (item) =>
      matchesQuery(item.name, q) || matchesQuery(item.category, q)
  );

  return {
    tab,
    mode,
    products,
    creatorsSeller,
    creatorsAffiliate,
    shopsSeller,
    shopsAffiliate,
    market_intel_placeholder: tab === "creator" || tab === "shop",
  };
}
