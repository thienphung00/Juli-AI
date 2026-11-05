import type { ShopeeAds, ShopeeFlows, ShopeeKeywordBoard, ShopeeProducts, ShopeePromotions } from "../../../lib/ops/types";
import type { ShopeeOrders } from "../../../lib/shopee-analytics/dashboards-client";

/** Synthetic payloads of the four Ops pages (P92 B-8), as the demo and the ops routes answer them. */

const RANGE = { from: "2026-10-01", to: "2026-10-30" };
const cell = { orders: 10, impressions: 1000, clicks: 50, buyers: 8 };
const numbers = { cpc_min: 400, cpc_max: 2200, difficulty: 56, competition: 90, opportunity: 1 };

export const FLOWS: ShopeeFlows = {
  range: RANGE,
  order_type: "confirmed",
  total_gmv: 1_200_000,
  total_orders: 12,
  flows: [
    { stream: "product_card", label: "Thẻ sản phẩm", gmv: 1_000_000, ...cell, has_total_row: true, children: [{ segment: "shop_page", label: "Trang shop", gmv: 300_000, ...cell }] },
    { stream: "seller_video", label: "Video", gmv: 200_000, ...cell, has_total_row: true, children: [] },
  ],
  ads_overlay: { stream: "ads", label: "Dịch vụ Hiển thị", gmv: 90_000, orders: 2, in_total: false },
  monthly: [{ month: "2026-10-01", streams: { product_card: 1_000_000, seller_video: 200_000 }, shop_page_gmv: 300_000 }],
  shop_monthly: [{ month: "2026-10-01", gmv: 1_200_000, orders: 12 }],
  has_data: true,
};

const FUNNEL = { impressions: 1000, clicks: 50, visitors: 40, page_views: 90, add_to_cart: 10, orders: 5, gmv: 800_000, units: 6, buyers: 4, ctr: 0.05, add_to_cart_rate: 0.25, click_to_order: 0.1 };

export const PRODUCTS: ShopeeProducts = {
  order_type: "confirmed",
  period: { from: "2026-09-29", to: "2026-10-28" },
  periods: [{ from: "2026-09-29", to: "2026-10-28", items: 1 }],
  items_total: 1,
  totals: FUNNEL,
  products: [
    {
      item_id: "111",
      name: "Sản phẩm thử",
      ...FUNNEL,
      by_flow: { product_card: { gmv: 600_000, orders: 4 } },
      history: [{ month: "2026-10-01", gmv: 800_000, orders: 5 }],
      flags: [{ flag: "ads_optimize", label: "Nên tối ưu quảng cáo", from: "2026-10-01", to: "2026-10-28" }],
    },
  ],
  shop_monthly: [],
  has_data: true,
};

const AD = (ad_type: string, label: string, cost: number, gmv: number, orders: number) => ({ ad_type, label, cost, gmv, orders, roas: gmv / cost, cost_per_order: cost / orders });

export const ADS: ShopeeAds = {
  range: RANGE,
  order_type: "placed",
  total: { cost: 600_000, gmv: 720_000, orders: 12, roas: 1.2, cost_per_order: 50_000 },
  by_type: [AD("ads_auto_bid", "GMV tối đa tự động đấu thầu", 600_000, 720_000, 12)],
  daily: [{ day: "2026-10-01", by_type: [AD("ads_auto_bid", "x", 100_000, 120_000, 2)] }],
  monthly: [{ month: "2026-10-01", cost: 600_000, gmv: 720_000, orders: 12, roas: 1.2, cost_per_order: 50_000, by_type: [AD("ads_auto_bid", "x", 600_000, 720_000, 12)] }],
  campaigns: [],
  campaigns_available: false,
  alerts: [{ ad_type: "ads_auto_bid", label: "GMV tối đa tự động đấu thầu", days: 6, from: "2026-10-01", to: "2026-10-06", roas: 1.2, floor: 1.5 }],
  alert_rule: { floor: 1.5, min_days: 5 },
  has_data: true,
};

export const PROMOS: ShopeePromotions = {
  range: RANGE,
  order_type: "confirmed",
  programs: [{ promo_type: "discount", type_label: "Khuyến mãi", name: "Chương trình thử", starts_at: "2026-10-02T00:00:00", ends_at: "2026-10-05T00:00:00", status: "Đã kết thúc", gmv: 700_000, orders: 7, units: 9, buyers: 6 }],
  daily: [],
  has_data: true,
};

export const BOARD: ShopeeKeywordBoard = {
  min_volume: 100,
  collection_dates: ["2026-11-03"],
  coverage: { da_tra: 1, khong_khop: 0, bi_chan: 0, chua_tra: 1 },
  to_look_up: ["miếng rửa chén"],
  keywords: [
    {
      id: "k1",
      keyword: "nước rửa chén",
      pattern: "type_function",
      enabled: true,
      coverage: "da_tra",
      products: [{ item_id: "3", name: "Nước rửa chén thử nghiệm" }],
      latest: { collected_on: "2026-11-03", volume: 300, ...numbers },
      history: [{ collected_on: "2026-11-03", volume: 300 }],
      related: [],
    },
    { id: "k2", keyword: "miếng rửa chén", pattern: "type_function", enabled: true, coverage: "chua_tra", products: [{ item_id: "1", name: "Miếng thử nghiệm" }], latest: null, history: [], related: [] },
  ],
  products: [{ item_id: "3", name: "Nước rửa chén thử nghiệm", keywords: 1, best_volume: 300, status: "co_tu_khoa" }],
};

export const ORDERS: ShopeeOrders = {
  platform: "shopee",
  order_basis: { key: "confirmed", label: "Đơn đã xác nhận" },
  window: { from: "2026-10-01", to: "2026-10-30", days: 30 },
  sort: "date",
  count: 2,
  offset: 0,
  limit: 100,
  by_status: { delivered: 1, cancelled: 1 },
  privacy: "Mã đơn là khoá băm rút gọn; không có thông tin người mua.",
  orders: [
    {
      order_key: "0000000000a1",
      ordered_on: "2026-10-07",
      status: "delivered",
      lines: 1,
      units: 1,
      items: ["1001"],
      levers: ["voucher"],
      gmv: 90_000,
      voucher: 2_000,
      promo_discount: 10_000,
      combo_discount: 0,
      paid_amount: 88_000,
      fees: 18_000,
      fee_source: "formula",
      cogs: 30_000,
      contribution: 38_000,
      income: { payout: 65_000, fees_total: 18_000, refund: null, net_shipping_cost: 0 },
    },
    {
      order_key: "0000000000b2",
      ordered_on: "2026-10-08",
      status: "cancelled",
      lines: 1,
      units: 2,
      items: ["1002"],
      levers: [],
      gmv: 120_000,
      voucher: 0,
      promo_discount: 0,
      combo_discount: 0,
      paid_amount: 120_000,
      fees: null,
      fee_source: null,
      cogs: 50_000,
      contribution: null,
      income: null,
    },
  ],
};
