import type { ShopeeApi } from "../client";
import type {
  Critical,
  FiveNumbers,
  FlowRow,
  LeverRow,
  Matrix,
  MatrixProduct,
  Overview,
  ProductPage,
  Ranking,
  SkuCost,
} from "../types";

/**
 * Synthetic payloads in the shape of `services/shopee_analytics` (household-goods shop of the
 * artboards; invented numbers, no shop data). Each factory takes a patch so a test changes only
 * what it is about.
 */

export const WINDOW = { from: "2026-10-04", to: "2026-11-02", days: 30 } as const;
export const PREVIOUS = { from: "2026-09-04", to: "2026-10-03", days: 30 } as const;

function flow(key: string, label: string, p: Partial<FlowRow> = {}): FlowRow {
  return {
    key,
    label,
    is_residual: false,
    views: 10000,
    clicks: 500,
    orders: 50,
    gmv: 10_000_000,
    ctr: 0.05,
    ctor: 0.1,
    aov: 200_000,
    share_pct: 20,
    identity_gmv: 10_000_000,
    identity_ok: true,
    gmv_previous: 9_000_000,
    gmv_change_pct: 11.1,
    ...p,
  };
}

export function flows(): Overview["flows"] {
  const rows = [
    flow("the_san_pham_khac", "Thẻ sản phẩm (ngoài Trang shop)", { gmv: 28_000_000, orders: 140, views: 50000, clicks: 2000, ctr: 0.04, ctor: 0.07, aov: 200_000, share_pct: 56 }),
    flow("trang_shop", "Trang shop", { gmv: 6_000_000, orders: 30, views: 5000, clicks: 400, ctr: 0.08, ctor: 0.075, aov: 200_000, share_pct: 12 }),
    flow("live", "Live", { gmv: 3_000_000, orders: 15, views: 2000, clicks: 100, ctr: 0.05, ctor: 0.15, aov: 200_000, share_pct: 6 }),
    flow("video", "Video", { gmv: 7_000_000, orders: 35, views: 8000, clicks: 300, ctr: 0.0375, ctor: 0.1167, aov: 200_000, share_pct: 14 }),
    flow("lien_ket", "Tiếp thị liên kết (Affiliate)", { gmv: 5_500_000, orders: 27, views: 3000, clicks: 200, ctr: 0.0667, ctor: 0.135, aov: 203_704, share_pct: 11 }),
    flow("chenh_lech_nguon", "Chênh lệch nguồn", { is_residual: true, views: null, clicks: null, orders: 3, gmv: 500_000, ctr: null, ctor: null, aov: null, share_pct: 1, identity_gmv: null, gmv_previous: null, gmv_change_pct: null }),
  ];
  return {
    available: true,
    basis: "exact",
    rows,
    total_gmv: 50_000_000,
    total_orders: 250,
    gmv_sum: 50_000_000,
    orders_sum: 250,
    adds_up: true,
    has_residual: true,
    the_san_pham_children: {
      rows: [
        { key: "search", label: "Tìm kiếm", views: 20000, clicks: 900, orders: 60, gmv: 12_000_000 },
        { key: "recommend", label: "Đề xuất", views: 15000, clicks: 600, orders: 40, gmv: 8_000_000 },
        { key: "cart", label: "Giỏ hàng", views: 2000, clicks: 100, orders: 8, gmv: 1_600_000 },
        { key: "my_orders", label: "Đơn mua của tôi", views: 1500, clicks: 100, orders: 6, gmv: 1_200_000 },
        { key: "promo", label: "Khuyến mãi", views: 8000, clicks: 200, orders: 20, gmv: 4_200_000 },
        { key: "other", label: "Khác", views: 3500, clicks: 100, orders: 6, gmv: 1_000_000 },
      ],
      gmv_sum: 28_000_000,
      parent_gmv: 28_000_000,
      note: "Sáu nguồn con là chi tiết của Thẻ sản phẩm (cộng cả Trang shop); không cộng vào tổng.",
    },
    chain: {
      views: 68000,
      clicks: 3000,
      orders: 250,
      ctr: 0.0441,
      ctor: 0.0833,
      aov: 200_000,
      gmv: 50_000_000,
      identity_gmv: 50_000_000,
      identity_ok: true,
      note: "Lượt xem cộng các luồng.",
    },
  };
}

export function five(p: Partial<FiveNumbers> = {}): FiveNumbers {
  return {
    discount: { vnd_before: 3_000_000, vnd_after: 4_200_000, pct_before: 6.2, pct_after: 8.4 },
    extra_revenue_per_extra_spend: { extra_revenue: 5_000_000, extra_spend: 2_000_000, per_vnd: 2.5, pct: 250, status: "ok", below_one: false },
    margin: { profit_before: null, profit_after: null, pct_before: 22.1, pct_after: 20.9, is_partial: true, cost_coverage_pct: 99.4 },
    orders: { before: 230, after: 250, change_pct: 8.7 },
    aov: { before: 195_000, after: 200_000, change_pct: 2.6 },
    spend_cap: { spend_per_day: 1_110_211, cap: 1_200_000, remaining: 89_789, used_pct: 92.5, over_cap: false },
    chi_definition: "chi = quảng cáo + voucher + khuyến mãi + combo + hoa hồng",
    comparison: { available: true, reason: null },
    ...p,
  };
}

function lever(key: string, label: string, p: Partial<LeverRow> = {}): LeverRow {
  return {
    key,
    label,
    orders: 100,
    gmv: 20_000_000,
    net_revenue: 18_000_000,
    contribution: 5_000_000,
    profit: 4_000_000,
    margin_pct: 20,
    aov: 200_000,
    orders_missing_profit: 0,
    orders_excluded: 0,
    share_pct: 40,
    ...p,
  };
}

export function overview(p: Partial<Overview> = {}): Overview {
  return {
    platform: "shopee",
    order_basis: { key: "confirmed", label: "Đơn đã xác nhận" },
    period: { window: WINDOW, previous: PREVIOUS, kind: "30d" },
    data: {
      shop_totals: { basis: "exact", days_covered: 30 },
      traffic: { basis: "exact", days_covered: 30 },
      ads_daily: { days_covered: 30 },
      order_lines: { lines: 300, days_with_orders: 30, window_days: 30, covers_window: true },
      product_flows: { source: "file", trang_shop_split: false },
    },
    warnings: [],
    kpi_strip: {
      gmv: { value: 50_000_000, previous: 46_900_000, change_pct: 6.6 },
      views: { value: 68000, previous: 66000, change_pct: 3.0 },
      ctr: { value: 0.0441, previous: 0.0455, change_pct: -3.1 },
      ctor: { value: 0.0833, previous: 0.0801, change_pct: 4.0 },
      aov: { value: 200_000, previous: 195_000, change_pct: 2.6 },
      orders: { value: 250, previous: 230, change_pct: 8.7 },
      margin_pct: { value: 20.9, previous: 22.1, label: "trên 99,4 % doanh thu có giá vốn (trong đó giả định 12,0 %)" },
    },
    gmv: {
      shopee_gmv: 50_000_000,
      shopee_orders: 250,
      aov_gmv: 200_000,
      aov_seller_centre: 192_000,
      aov_note: "AOV Seller Centre = (GMV − voucher shop) ÷ đơn đã xác nhận (§14); AOV chuỗi = GMV ÷ đơn.",
      line_gmv: 49_800_000,
      line_orders: 249,
    },
    flows: flows(),
    levers: {
      rows: [
        lever("khong_uu_dai", "Không ưu đãi", { orders: 120, gmv: 24_000_000, share_pct: 48 }),
        lever("voucher", "Voucher shop", { orders: 70, gmv: 14_000_000, share_pct: 28, margin_pct: 18 }),
        lever("khuyen_mai", "Khuyến mãi", { orders: 40, gmv: 8_000_000, share_pct: 16, margin_pct: 15 }),
        lever("combo", "Combo", { orders: 19, gmv: 3_800_000, share_pct: 7.6, margin_pct: 24 }),
      ],
      gmv_sum: 49_800_000,
      gmv_total: 49_800_000,
      adds_up: true,
      note: "Mỗi dòng đơn một ưu đãi: combo > khuyến mãi > voucher > không ưu đãi.",
    },
    five_numbers: five(),
    profit: {
      profit_vnd: null,
      profit_on_covered_vnd: 8_900_000,
      margin_pct: 20.9,
      margin_basis: "profit ÷ doanh thu thực (sau voucher và combo)",
      contribution_before_ads: 15_000_000,
      net_revenue: 45_000_000,
      orders: 249,
      cost_coverage: { net_revenue: 45_000_000, real_pct: 88, assumed_pct: 11.4, unknown_pct: 0.6, packaging_assumed_pct: 5, label: "giá vốn giả định (1/3 giá niêm yết) khi chưa nhập giá vốn thật" },
      assumed_cost_share_pct: 11.4,
      assumed_cost_label: "giá vốn giả định (1/3 giá)",
      profit_is_partial: true,
      ad_spend: { total: 4_000_000, by_product: 3_400_000, unattributed: 600_000, zero_revenue_campaigns: 100_000, consistent: true, unattributed_label: "QC không gắn sản phẩm / không ra đơn" },
      other_marketing_costs: 300_000,
      break_even_roas: 3.2,
      gmv_reconciliation: { line_gmv: 49_800_000, shopee_gmv: 50_000_000, gap: -200_000, gap_pct: -0.4, warn: false },
      missing: { cogs: 12 },
    },
    ads: {
      basis: { key: "placed", label: "đơn đã đặt" },
      note: "Quảng cáo tính theo đơn đã đặt (cách Shopee báo cáo); không cộng vào tổng đơn đã xác nhận.",
      in_which: "trong đó (overlay, không phải một dòng của tổng)",
      spend: 4_000_000,
      gmv_placed: 16_000_000,
      orders_placed: 80,
      roas: 4,
      spend_per_day: 133_333,
      allocation: { basis: "exact", label: "báo cáo trùng kỳ" },
    },
    targets: { margin_pct: 10, daily_marketing_cap: 1_200_000 },
    ...p,
  };
}

function productFlows(trangShop: boolean): MatrixProduct["flows"] {
  const rows = [
    flow("the_san_pham_khac", "Thẻ sản phẩm (ngoài Trang shop)", { views: 4000, clicks: 200, orders: 20, gmv: 4_000_000, ctr: 0.05, ctor: 0.1, aov: 200_000, share_pct: 57 }),
    flow("trang_shop", "Trang shop", { views: 1000, clicks: 50, orders: 5, gmv: 1_000_000, ctr: 0.05, ctor: 0.1, aov: 200_000, share_pct: 14 }),
    flow("live", "Live", { views: 500, clicks: 20, orders: 2, gmv: 400_000, ctr: 0.04, ctor: 0.1, aov: 200_000, share_pct: 6 }),
    flow("video", "Video", { views: 1500, clicks: 60, orders: 6, gmv: 1_200_000, ctr: 0.04, ctor: 0.1, aov: 200_000, share_pct: 17 }),
    flow("lien_ket", "Tiếp thị liên kết (Affiliate)", { views: 500, clicks: 20, orders: 2, gmv: 400_000, ctr: 0.04, ctor: 0.1, aov: 200_000, share_pct: 6 }),
  ];
  return {
    rows,
    total_gmv: 7_000_000,
    total_orders: 35,
    gmv_sum: 7_000_000,
    orders_sum: 35,
    adds_up: true,
    has_residual: false,
    trang_shop_available: trangShop,
  };
}

export function matrixProduct(id: string, p: Partial<MatrixProduct> = {}): MatrixProduct {
  return {
    product_id: id,
    name: `Sản phẩm ${id}`,
    gmv: 7_000_000,
    gmv_basis: "shopee_product_period",
    orders: 35,
    line_gmv: 6_900_000,
    line_orders: 34,
    profit: { profit: 1_400_000, margin_pct: 20, contribution: 1_800_000, net_revenue: 6_300_000, ad_spend: 400_000, break_even_roas: 3, cost_coverage_pct: 100, assumed_cost: false },
    flows: productFlows(true),
    levers: [
      lever("khong_uu_dai", "Không ưu đãi", { orders: 15, gmv: 3_000_000 }),
      lever("voucher", "Voucher shop", { orders: 10, gmv: 2_000_000 }),
      lever("khuyen_mai", "Khuyến mãi", { orders: 6, gmv: 1_200_000 }),
      lever("combo", "Combo", { orders: 4, gmv: 700_000 }),
    ],
    ads: { basis: { key: "placed", label: "đơn đã đặt" }, note: "Quảng cáo tính theo đơn đã đặt.", spend: 400_000, gmv_placed: 1_600_000, direct_gmv_placed: 1_200_000, roas_broad: 4, roas_direct: 3, break_even_roas: 3, below_break_even: false },
    ...p,
  };
}

export function matrix(p: Partial<Matrix> = {}): Matrix {
  return {
    platform: "shopee",
    window: WINDOW,
    sort: "gmv",
    products: [
      matrixProduct("BEP-S5", { name: "Bộ vệ sinh bếp 5 món", gmv: 12_000_000, orders: 60, card: { id: "c_bep_voucher", title: "Voucher 10.000đ", at_stake_per_month: 1_500_000 } }),
      matrixProduct("GL-001", { name: "Găng tay cao su đa dụng", gmv: 9_000_000, orders: 50, profit: { profit: 900_000, margin_pct: 8, contribution: 1_300_000, net_revenue: 8_000_000, ad_spend: 400_000, break_even_roas: 3, cost_coverage_pct: 88.8, assumed_cost: true }, flows: productFlows(false) }),
      matrixProduct("XM-003", { name: "Xơ mướp rửa chén", gmv: 5_000_000, orders: 25, flows: null }),
    ],
    product_count: 3,
    ads_basis: { key: "placed", label: "đơn đã đặt" },
    sums: { gmv_shopee_products: 26_000_000, gmv_shop: 50_000_000, note: "Σ GMV sản phẩm khớp Doanh số shop khi file sản phẩm đúng kỳ; phần lệch hiện ở dòng Chênh lệch nguồn." },
    ...p,
  };
}

export function critical(p: Partial<Critical> = {}): Critical {
  const base = {
    level: "product" as const,
    product_id: "XM-003",
    flow: null,
    flow_label: null,
    change_kinds: ["price"],
    assumed_cost: false,
    money_basis: "confirmed",
  };
  return {
    platform: "shopee",
    window: WINDOW,
    items: [
      {
        ...base,
        id: "flow:the_san_pham_khac:ctor",
        kind: "below_band",
        level: "flow",
        product_id: null,
        name: null,
        flow: "the_san_pham_khac",
        flow_label: "Thẻ sản phẩm (ngoài Trang shop)",
        kpi: "ctor",
        current: 0.07,
        reference: { type: "band", label: "dải bình thường", value: 0.085, low: 0.08, high: 0.09 },
        deviation_pct: -17.6,
        at_stake_per_day: 300_000,
        at_stake_per_month: 9_000_000,
        cause: { stage: "ctor", text: "Khách bấm vào nhưng ít đặt đơn." },
        ranking_link: { kpi: "ctor", src: "the_san_pham_khac", focus: "the_san_pham_khac" },
        rank: 1,
        card: { id: "c_xm_disc", title: "Giảm giá" },
      },
      {
        ...base,
        id: "product:GL-001:bien",
        kind: "margin_below_target",
        kpi: "bien",
        name: "Găng tay cao su đa dụng",
        product_id: "GL-001",
        current: 8,
        reference: { type: "target", label: "mục tiêu biên", value: 10 },
        deviation_pct: -20,
        at_stake_per_day: 120_000,
        at_stake_per_month: 3_600_000,
        cause: { stage: "bien", text: "Biên dưới mục tiêu." },
        ranking_link: { kpi: "bien", src: "all", focus: "GL-001" },
        assumed_cost: true,
        rank: 2,
        card: null,
      },
      {
        ...base,
        id: "product:XM-003:roas",
        kind: "roas_below_break_even",
        kpi: "roas",
        name: "Xơ mướp rửa chén",
        current: 2.1,
        reference: { type: "break_even", label: "ROAS hoà vốn (trực tiếp)", value: 3 },
        deviation_pct: -30,
        at_stake_per_day: 50_000,
        at_stake_per_month: 1_500_000,
        money_basis: "placed",
        cause: { stage: "roas", text: "Quảng cáo đang lỗ." },
        ranking_link: { kpi: "roas", src: "ads", focus: "XM-003" },
        rank: 3,
        card: null,
      },
    ],
    in_band: [
      {
        ...base,
        id: "flow:video:ctr",
        kind: "below_band",
        level: "flow",
        product_id: null,
        name: null,
        flow: "video",
        flow_label: "Video",
        kpi: "ctr",
        current: 0.04,
        reference: { type: "band", label: "dải", value: 0.04, low: 0.035, high: 0.045 },
        deviation_pct: 0,
        at_stake_per_day: 0,
        at_stake_per_month: 0,
        cause: { stage: "ctr", text: "" },
        ranking_link: { kpi: "ctr", src: "video", focus: "video" },
      },
    ],
    total_at_stake_per_day: 470_000,
    notes: [{ code: "assumed_cost", message: "Một số mục dùng giá vốn giả định (1/3 giá)." }],
    ranking_rule: "Xếp theo ₫ mỗi ngày đang bị ảnh hưởng nếu chỉ số về mức tham chiếu của nó.",
    ...p,
  };
}

function rrow(id: string, label: string, now: number, before: number, delta: number, p: Partial<Ranking["down"] extends readonly (infer R)[] | undefined ? R : never> = {}) {
  return {
    id,
    label,
    now,
    before,
    delta,
    quantity: { orders_now: 40, orders_before: 50 },
    spend: null,
    confidence: "Rõ",
    before_missing: false,
    link: { kpi: "gmv_per_day", focus: id },
    product_id: id,
    ...p,
  };
}

export function ranking(p: Partial<Ranking> = {}): Ranking {
  const down = [
    rrow("XM-003", "Xơ mướp rửa chén", 100_000, 200_000, -100_000, { card: { id: "c_xm_disc", title: "Giảm giá", at_stake_per_month: 3_000_000 } }),
    rrow("GN-005", "Giấy bạc nhôm 5m", 50_000, 80_000, -30_000, { confidence: "Tham khảo" }),
  ];
  const up = [rrow("BEP-S5", "Bộ vệ sinh bếp 5 món", 300_000, 250_000, 50_000)];
  const closingDown = [
    { label: "2 sản phẩm ít đơn", delta: -5_000 },
    { label: "Các sản phẩm khác", delta: -2_000 },
    { label: "Các sản phẩm kéo lên", delta: 50_000 },
    { label: "Thay đổi cơ cấu sản phẩm", delta: -3_000 },
  ];
  // Σ down rows (−130.000) + closing (+40.000) = cell delta −90.000
  const closingUp = [
    { label: "2 sản phẩm ít đơn", delta: -5_000 },
    { label: "Các sản phẩm khác", delta: -2_000 },
    { label: "Các sản phẩm kéo xuống", delta: -130_000 },
    { label: "Thay đổi cơ cấu sản phẩm", delta: -3_000 },
  ];
  return {
    platform: "shopee",
    kind: "products",
    source: "all",
    sub: null,
    xep_theo: { key: "gmv_per_day", label: "₫ GMV / ngày", additive: true },
    window: WINDOW,
    previous: PREVIOUS,
    order_basis: { key: "confirmed", label: "Đơn đã xác nhận" },
    ads_basis: null,
    ads_note: null,
    supported: true,
    cell: { now: 450_000, before: 540_000, delta: -90_000 },
    down,
    up,
    closing: {
      few: { label: "2 sản phẩm ít đơn", delta: -5_000, count: 2 },
      others: { label: "Các sản phẩm khác", delta: -2_000, count: 4 },
      mix: { label: "Thay đổi cơ cấu sản phẩm", delta: -3_000 },
    },
    views: {
      down: { rows: down, closing: closingDown, sum: -90_000, cell_delta: -90_000 },
      up: { rows: up, closing: closingUp, sum: -90_000, cell_delta: -90_000 },
    },
    adds_up: true,
    adds_up_note: null,
    row_count: 9,
    ...p,
  };
}

function sku(id: string, p: Partial<SkuCost> = {}): SkuCost {
  return {
    sku: id,
    units: 30,
    list_price: 200_000,
    waterfall_per_unit: {
      list: 200_000,
      promo_discount: 0,
      shop_voucher: 10_000,
      combo: 0,
      net_revenue: 190_000,
      platform_fees: 28_500,
      cogs: 100_000,
      packaging: 3_000,
      commission: 0,
      contribution_before_ads: 58_500,
      ads: 35_000,
      profit: 23_500,
      margin_pct: 12.4,
      organic_vs_ads: "unknown (đơn xuất không ghi nguồn quảng cáo)",
    },
    cost: { cogs_per_unit: 100_000, cogs_source: "real", packaging: 3_000, packaging_source: "real", label: null },
    fee: { fixed_fee_rate_pct: 0, rate_source: "formula", category: null, platform_fee_rate_pct: 15, fixed_per_order: 0 },
    floor: { absolute: 121_176, operating: 181_979, max_discount_pct: 9, max_discount_amount: 18_000, reasons: {}, net_revenue_per_unit: 190_000, breach: null, margin_target_pct: 10 },
    ...p,
  };
}

export function product(p: Partial<ProductPage> = {}): ProductPage {
  const kpi = (days: number) => ({
    gmv: { value: 7_000_000, previous: 6_000_000, change_pct: 16.7 },
    orders: { value: 35, previous: 30 },
    views: 7500,
    clicks: 350,
    ctr: 0.0467,
    ctor: 0.1,
    aov: 200_000,
    profit: matrixProduct("BEP-S5").profit,
    five_numbers: five({ margin: { profit_before: 1_100_000, profit_after: 1_400_000, pct_before: 18, pct_after: 20, is_partial: false, cost_coverage_pct: 100 } }),
    basis: { gmv: "shopee_product_period", flows: { days } },
  });
  return {
    platform: "shopee",
    order_basis: { key: "confirmed", label: "Đơn đã xác nhận" },
    period: { selected: "30d", window: WINDOW, previous: PREVIOUS },
    header: {
      product_id: "BEP-S5",
      title: "Bộ vệ sinh bếp 5 món set rửa chén",
      title_chars: 35,
      seller_sku: "BEP-S5-CB",
      status: "NORMAL",
      category_path: ["Nhà Cửa & Đời Sống", "Dụng Cụ Nhà Bếp", "Bộ Dụng Cụ Vệ Sinh Bếp"],
      images: ["https://img.example/bep-s5-1.jpg", "https://img.example/bep-s5-2.jpg"],
      price: { list: 200_000, current: 190_000, promo_label: "Voucher shop 10.000đ", source: "snapshot", captured_at: "2026-11-03T06:10:00Z" },
      stock: { value: 42, age_days: 3, stale: true },
      reputation: { rating: 4.8, rating_count: 1236, likes: 892, sold_total: 3420 },
      variations: [
        { variation_id: "v1", name: "Cơ bản", seller_sku: "BEP-S5-CB", status: "NORMAL" },
        { variation_id: "v2", name: "Quà tặng", seller_sku: "BEP-S5-QT", status: "NORMAL" },
      ],
      missing_fields: [],
    },
    kpi_by_period: { "7d": kpi(7), "30d": kpi(30), "90d": kpi(90) },
    nguon: matrixProduct("BEP-S5", { name: "Bộ vệ sinh bếp 5 món", card: { id: "c_bep_voucher", title: "Voucher", at_stake_per_month: 1_500_000 } }),
    ads: matrixProduct("BEP-S5").ads,
    cost_and_floor: {
      skus: [sku("BEP-S5-CB"), sku("BEP-S5-QT", { cost: { cogs_per_unit: 33_333, cogs_source: "assumed", packaging: 0, packaging_source: "assumed", label: "giá vốn giả định (1/3 giá)" } })],
      coverage_label: "giá vốn giả định (1/3 giá)",
      floor_note: "Giá sàn tuyệt đối = (giá vốn + đóng gói + phí cố định/đơn) ÷ (1 − phí sàn %).",
    },
    keywords: {
      roles: {
        chinh: { label: "Chính", keywords: ["bộ vệ sinh bếp", "set rửa chén", "găng tay rửa chén", "xơ mướp", "túi zip"].map((k, i) => ({ keyword: k, pattern: null, in_title: i < 3, title_position: i < 3 ? i * 10 : null, within_counted_chars: i < 3 ? true : null, market: { volume: 1000 * (i + 1), cpc_min: 500, cpc_max: 900, difficulty: 40, collected_on: "2026-11-01" }, ads_placed: null })) },
        phu: { label: "Phụ", keywords: [{ keyword: "dụng cụ bếp", pattern: null, in_title: false, title_position: null, within_counted_chars: null, market: null, ads_placed: { spend: 100_000, gmv: 400_000, orders: 2 } }] },
        thuong_hieu: { label: "Thương hiệu", keywords: [] },
        loai_tru: { label: "Loại trừ", keywords: [{ keyword: "cũ", pattern: null, in_title: false, title_position: null, within_counted_chars: null, market: null, ads_placed: null }] },
      },
      core: { used: 5, max: 5, full: true, in_title: 3, coverage_pct: 60 },
      title_counted_chars: 100,
    },
    ...p,
  };
}

/** A fake API: every method resolves with the given payload (or rejects). */
export function fakeApi(
  data: Partial<{ overview: Overview; matrix: Matrix; critical: Critical; ranking: Ranking; product: ProductPage }> = {},
  failWith?: Error,
): ShopeeApi & { calls: string[] } {
  const calls: string[] = [];
  const answer = <T,>(name: string, value: T | undefined, args: unknown): Promise<T> => {
    calls.push(`${name}:${JSON.stringify(args)}`);
    if (failWith) return Promise.reject(failWith);
    return Promise.resolve(value as T);
  };
  return {
    calls,
    overview: (q) => answer("overview", data.overview ?? overview(), q),
    matrix: (q) => answer("matrix", data.matrix ?? matrix(), q),
    critical: (q) => answer("critical", data.critical ?? critical(), q),
    ranking: (q) => answer("ranking", data.ranking ?? ranking(), q),
    product: (id, period) => answer("product", data.product ?? product(), { id, period }),
  };
}
