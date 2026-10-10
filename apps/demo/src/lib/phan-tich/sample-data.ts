/**
 * The signed-out Phân tích sample ("Bản minh họa", ADR-109 Amendment 2): the
 * same invented cosmetics shop as the Quyết định sample (`lib/quyet-dinh/
 * sample-data.ts` — SM-012, MN-015, KD-030, SR-007, TN-021 with the same
 * TikTok product ids), built in the exact wire shapes the signed-in door
 * reads — an ADR-108 report (`GET /v1/demo/analysis`) and ADR-109 d.5 ranking
 * tables (`GET /v1/demo/analysis/rankings`) — so both doors go through the
 * same mapping (`model.ts`, `rows.ts`, `extras.ts`).
 *
 * Figures follow the artboards (`docs/product/design/phan-tich/`) where they
 * are coherent; the four cells' ₫/day impacts are the artboards' and the
 * prior-window values are derived from them with ADR-108's log-share split,
 * so every Δ % agrees with its ₫/day, and every ranking reconciles to its
 * cell ("Tổng" = the cell's figure). Pure data — bundled, never fetched.
 */

import type {
  ChannelKey,
  ChannelRow,
  Counts,
  FunnelComparison,
  ShopAnalysisEnvelope,
  ShopDiagnosisReport,
} from "../shop-analysis/types";
import type { CellMetric } from "./model";
import type { ClosingRow, RankedMetric, RankedStream, RankingEnvelope, RankingRow, RowKind } from "./types";

/** The Quyết định sample's product id for a SKU (`sampleDecision`: `1729000` + the SKU's digits). */
export const sampleProductId = (sku: string) => `1729000${sku.replace(/\D/g, "")}`;

const PRODUCTS: ReadonlyArray<readonly [string, string]> = [
  ["SM-012", "Son môi số 12"],
  ["MN-015", "Mặt nạ đất sét 100g"],
  ["KD-030", "Kem dưỡng ẩm ceramide"],
  ["SR-007", "Sữa rửa mặt amino 150ml"],
  ["TN-021", "Toner rau má 200ml"],
  ["KC-004", "Kem chống nắng SPF50+"],
];
const NAME: Readonly<Record<string, string>> = Object.fromEntries(PRODUCTS);
const id = sampleProductId;

const END = "2026-10-06";
const WINDOWS = { prior_first: "2026-08-08", prior_last: "2026-09-06", last_first: "2026-09-07", last_last: END };
const AS_OF = END;
const BUILT_AT = "2026-10-07T01:00:00Z";

// -- streams --------------------------------------------------------------------------------

interface StreamTargets {
  /** Last-window daily values: impressions, CTR, CTOR, AOV. */
  readonly last: Readonly<Record<CellMetric, number>>;
  /** ₫/day each metric's change carried (the artboards' cell figures). */
  readonly contribution: Readonly<Record<CellMetric, number>>;
  readonly confidence: Readonly<Record<CellMetric, "Rõ" | "Tham khảo">>;
  readonly cart?: boolean;
}

const ORDER: readonly CellMetric[] = ["impressions", "ctr", "ctor", "aov"];

/** Only Tab cửa hàng's SKU orders are estimated (CTOR × clicks): TikTok gives none there. */
function counts(values: Readonly<Record<CellMetric, number>>, cart: boolean, estimated: boolean): Counts {
  const clicks = values.impressions * values.ctr;
  const orders = clicks * values.ctor;
  return {
    impressions: values.impressions,
    clicks,
    add_to_cart: cart ? orders / 0.45 : null,
    sku_orders: orders,
    gmv: orders * values.aov,
    orders_estimated: estimated,
  };
}

/** Prior values such that the log-share split of the GMV change gives `contribution`. */
function channel(stream: ChannelKey, t: StreamTargets): ChannelRow {
  const gmvLast = ORDER.reduce((product, m) => product * t.last[m], 1);
  const change = ORDER.reduce((sum, m) => sum + t.contribution[m], 0);
  const logR = Math.log(gmvLast / (gmvLast - change));
  const prior = Object.fromEntries(
    ORDER.map((m) => [m, t.last[m] / Math.exp((logR * t.contribution[m]) / change)]),
  ) as Record<CellMetric, number>;
  return {
    channel: stream,
    comparison: {
      prior: counts(prior, t.cart ?? false, stream === "shop_tab"),
      last: counts(t.last, t.cart ?? false, stream === "shop_tab"),
      factors: ORDER.map((m) => ({
        factor: m,
        prior: prior[m],
        last: t.last[m],
        contribution: t.contribution[m],
        confidence: t.confidence[m],
      })),
    },
    share_of_change: null,
    additive: stream !== "shop_tab",
  };
}

const RO = "Rõ" as const;
const TK = "Tham khảo" as const;

const STREAMS: Readonly<Record<RankedStream, StreamTargets>> = {
  product_card: {
    last: { impressions: 9913, ctr: 0.0444, ctor: 0.0514, aov: 160_000 },
    contribution: { impressions: 620_000, ctr: -12_000, ctor: -250_000, aov: -105_000 },
    confidence: { impressions: RO, ctr: TK, ctor: RO, aov: RO },
    cart: true,
  },
  shop_tab: {
    last: { impressions: 2118, ctr: 0.0583, ctor: 0.0714, aov: 167_000 },
    contribution: { impressions: -24_000, ctr: -4_000, ctor: 29_000, aov: -31_000 },
    confidence: { impressions: TK, ctr: TK, ctor: RO, aov: RO },
  },
  seller_video: {
    last: { impressions: 5630, ctr: 0.0292, ctor: 0.0668, aov: 173_000 },
    contribution: { impressions: 38_000, ctr: -96_000, ctor: -50_000, aov: -15_000 },
    confidence: { impressions: TK, ctr: RO, ctor: TK, aov: TK },
  },
  seller_live: {
    last: { impressions: 1410, ctr: 0.0486, ctor: 0.071, aov: 164_000 },
    contribution: { impressions: 41_000, ctr: 12_000, ctor: -22_000, aov: -1_000 },
    confidence: { impressions: RO, ctr: TK, ctor: RO, aov: TK },
  },
};

/**
 * Liên kết (affiliate creators' videos and LIVEs): not a Phân tích stream (Juli
 * does not act on it), but Trang chủ's matrix shows it greyed "chỉ theo dõi"
 * (ADR-109 d.3), so the shared sample carries it too.
 */
const AFFILIATE: StreamTargets = {
  last: { impressions: 3270, ctr: 0.0312, ctor: 0.0524, aov: 158_000 },
  contribution: { impressions: 62_000, ctr: -9_000, ctor: 6_000, aov: -4_000 },
  confidence: { impressions: TK, ctr: TK, ctor: TK, aov: TK },
};

/** Additive streams' counts summed — the shop-wide row Trang chủ's GMV / Đơn / AOV cards read. */
function shopTotal(rows: readonly ChannelRow[]): FunnelComparison {
  const sum = (window: "prior" | "last"): Counts => {
    const parts = rows.filter((r) => r.additive).map((r) => r.comparison[window]);
    const add = (read: (c: Counts) => number | null) =>
      parts.reduce((acc, c) => acc + (read(c) ?? 0), 0);
    return {
      impressions: add((c) => c.impressions),
      clicks: add((c) => c.clicks),
      add_to_cart: null,
      sku_orders: add((c) => c.sku_orders),
      gmv: add((c) => c.gmv),
    };
  };
  return { prior: sum("prior"), last: sum("last"), factors: [] };
}

// -- daily GMV, promotions -------------------------------------------------------------------

/** PtProduct's 60 bars (index 0 = 08/08), × 180k ₫. */
const BASE = [
  31, 33, 30, 34, 32, 35, 33, 31, 36, 34, 33, 35, 37, 34, 32, 35, 36, 38, 35, 34, 33, 36, 35, 37, 34, 36, 38, 35, 37, 36,
  37, 38, 36, 38, 36, 37, 35, 39, 38, 36, 37, 40, 37, 37, 36, 38, 37, 39, 36, 38, 35, 37, 39, 36, 38, 40, 37, 36, 38, 39,
];
const NINE_NINE = 32;
const FLASH_DAYS = [12, 26, 27, 43, 44, 50, 51, 57];

function isoDay(index: number): string {
  return new Date(Date.parse(`${WINDOWS.prior_first}T00:00:00Z`) + index * 86_400_000).toISOString().slice(0, 10);
}

function dailyGmv(): Record<string, number> {
  const out: Record<string, number> = {};
  BASE.forEach((value, i) => {
    let units = value;
    if (i === NINE_NINE) units = 68;
    else if (i === 43) units = 50;
    else if (FLASH_DAYS.includes(i)) units = Math.round(value * 1.15);
    out[isoDay(i)] = units * 180_000;
  });
  return out;
}

function flashCoverage(): Record<string, number> {
  return Object.fromEntries(BASE.map((_, i) => [isoDay(i), FLASH_DAYS.includes(i) ? 1 : 0]));
}

function profile(sku: string, channels: Partial<Record<RankedStream, [number, number]>>) {
  return {
    product_id: id(sku),
    title: NAME[sku],
    channels: Object.entries(channels).map(([stream, [prior, last]]) => ({
      channel: stream,
      comparison: {
        prior: { impressions: 1, clicks: 0, add_to_cart: null, sku_orders: null, gmv: prior },
        last: { impressions: 1, clicks: 0, add_to_cart: null, sku_orders: null, gmv: last },
        factors: [],
      },
      share_of_change: null,
      additive: true,
    })),
  };
}

export function sampleReport(): ShopDiagnosisReport {
  const flashBand = (index: number, title: string, products: number) => ({
    kind: "Flash sale",
    title,
    first: isoDay(index),
    last: isoDay(index),
    days_prior: index < 30 ? 1 : 0,
    days_last: index < 30 ? 0 : 1,
    product_count: products,
  });
  const channels: ChannelRow[] = [
    ...(Object.keys(STREAMS) as RankedStream[]).map((s) => channel(s, STREAMS[s])),
    channel("affiliate", AFFILIATE),
  ];
  const report = {
    shop_name: "Cửa hàng Mẫu Hoa Mai",
    end: END,
    windows: WINDOWS,
    ranking: "60d",
    missing_days: [],
    sale_days: [isoDay(NINE_NINE)],
    total: shopTotal(channels),
    channels,
    affiliate_rows: [],
    groups: [],
    timelines: [],
    shop_bands: [
      flashBand(12, "Flash sale 20/08", 2),
      flashBand(26, "Flash cuối tuần 03/09", 2),
      flashBand(43, "Flash sale 20/09", 3),
      flashBand(50, "Flash cuối tuần 27/09", 3),
      flashBand(57, "Flash sale 04/10", 2),
    ],
    shop_flash: {
      coverage: flashCoverage(),
      weekly: [],
      coverage_last: 5 / 30,
      coverage_prior: 3 / 30,
      flash_days_last: FLASH_DAYS.filter((i) => i >= 30).length,
      flash_days_prior: FLASH_DAYS.filter((i) => i < 30).length,
      true_depth: 0.09,
      list_depth: 0.18,
      cells: [],
      flags: [],
    },
    vouchers: {
      yardstick: { common_price: 160_000, closing_cut: 150_000, sample: 120 },
      live: [
        { voucher: { title: "Giảm 20k đơn từ 199k", threshold: 199_000, amount_off: 20_000 }, voucher_class: "Nâng giá trị đơn", above_after: 0.14 },
        { voucher: { title: "Giảm 10k", threshold: 99_000, amount_off: 10_000 }, voucher_class: "Chốt đơn", above_after: 0.09 },
      ],
      older_by_month: [],
    },
    selection: { ranking: "60d", heroes: [id("SM-012"), id("SR-007")], gmv_share: 0.6, movers: [], dispersed: false },
    profiles: [
      profile("SM-012", { product_card: [1_200_000, 1_400_000], seller_video: [300_000, 600_000], seller_live: [200_000, 210_000] }),
      profile("SR-007", { product_card: [700_000, 560_000], seller_video: [150_000, 155_000], seller_live: [240_000, 160_000] }),
    ],
    watch: [],
    titles: Object.fromEntries(PRODUCTS.map(([sku, name]) => [id(sku), name])),
    orders_present: true,
    daily_gmv: dailyGmv(),
    seller_skus: Object.fromEntries(PRODUCTS.map(([sku]) => [id(sku), sku])),
    promo_products: [
      { product_id: id("SM-012"), kind: "Giảm giá sản phẩm", days: 21, depth: 0.02, gmv_in: 1_300_000, gmv_out: 1_200_000 },
      { product_id: id("TN-021"), kind: "Flash sale", days: 5, depth: 0.12, gmv_in: 1_100_000, gmv_out: 700_000 },
      { product_id: id("MN-015"), kind: "Flash sale", days: 3, depth: 0.1, gmv_in: 900_000, gmv_out: 600_000 },
      { product_id: id("KD-030"), kind: "Giảm giá sản phẩm", days: 14, depth: 0.07, gmv_in: 600_000, gmv_out: 500_000 },
      { product_id: id("KC-004"), kind: "Flash sale", days: 2, depth: 0.08, gmv_in: 400_000, gmv_out: 300_000 },
    ],
  };
  return report as unknown as ShopDiagnosisReport;
}

export function sampleEnvelope(): ShopAnalysisEnvelope {
  return { as_of: AS_OF, built_at: BUILT_AT, ranking: "60d", report: sampleReport() };
}

// -- rankings ---------------------------------------------------------------------------------

type Conf = "Rõ" | "Tham khảo";
/** [sku, prior, last, ₫/day, confidence, quantity prior, quantity last, CTOR steps?] */
type ProductRow = readonly [string, number, number, number, Conf, number, number, ([number, number] | null)?];
/** [id, title, ISO day, product SKUs, prior, last, ₫/day, confidence, quantity last] */
type ContentRow = readonly [string, string, string, readonly string[], number, number, number, Conf, number];

interface TableSpec<R> {
  readonly down: readonly R[];
  readonly up: readonly R[];
  /** [few label, few ₫/day, others ₫/day]; the mix row closes the table on the cell figure. */
  readonly closing: readonly [string, number, number];
}

function productRow(row: ProductRow): RankingRow {
  const [sku, prior, last, gmv, confidence, q0, q1, steps] = row;
  return {
    id: id(sku),
    name: NAME[sku],
    gmv_per_day: gmv,
    confidence,
    prior,
    last,
    quantity_prior: q0,
    quantity_last: q1,
    seller_sku: sku,
    ...(steps ? { steps: { add_to_cart_rate: steps[0], orders_per_cart: steps[1] } } : {}),
  };
}

function contentRow(stream: RankedStream) {
  return (row: ContentRow): RankingRow => {
    const [rowId, title, day, skus, prior, last, gmv, confidence, quantity] = row;
    const [y, m, d] = day.split("-");
    return {
      id: rowId,
      name: stream === "seller_live" ? `${title} · ${d}/${m}/${y}` : title,
      gmv_per_day: gmv,
      confidence,
      prior,
      last,
      quantity_prior: null,
      quantity_last: quantity,
      date: day,
      product_ids: skus.map(id),
    };
  };
}

const NOUNS: Readonly<Record<RowKind, readonly [string, string]>> = {
  product: ["Các sản phẩm khác", "Thay đổi cơ cấu sản phẩm"],
  video: ["Các video khác", "Thay đổi cơ cấu video"],
  live_session: ["Các phiên LIVE khác", "Thay đổi cơ cấu phiên LIVE"],
};

function envelope(stream: RankedStream, metric: CellMetric, kind: RowKind, down: RankingRow[], up: RankingRow[], closing: readonly [string, number, number]): RankingEnvelope {
  const factor = STREAMS[stream].contribution[metric];
  const listed = [...down, ...up].reduce((sum, r) => sum + r.gmv_per_day, 0);
  const [fewLabel, few, others] = closing;
  const mix: ClosingRow = { label: NOUNS[kind][1], gmv_per_day: factor - listed - few - others };
  const row = channel(stream, STREAMS[stream]);
  const factorRow = row.comparison.factors.find((f) => f.factor === metric);
  return {
    as_of: AS_OF,
    built_at: BUILT_AT,
    stream,
    metric,
    ranking: {
      stream,
      metric,
      row_kind: kind,
      stream_prior: factorRow?.prior ?? null,
      stream_last: factorRow?.last ?? null,
      stream_factor_gmv: factor,
      down,
      up,
      closing: {
        few: { label: fewLabel, count: Number.parseInt(fewLabel, 10) || 0, gmv_per_day: few },
        others: { label: NOUNS[kind][0], count: 4, gmv_per_day: others },
        mix,
      },
    },
  };
}

const PRODUCT_TABLES: Readonly<Record<"product_card" | "shop_tab", Readonly<Record<CellMetric, TableSpec<ProductRow>>>>> = {
  product_card: {
    impressions: {
      down: [
        ["SR-007", 1820, 1410, -48_000, RO, 54_600, 42_300],
        ["KC-004", 960, 880, -12_000, TK, 28_800, 26_400],
      ],
      up: [
        ["SM-012", 2400, 3910, 410_000, RO, 72_000, 117_300],
        ["MN-015", 1650, 2140, 205_000, RO, 49_500, 64_200],
      ],
      closing: ["2 sản phẩm ít lượt hiển thị", 4_000, 21_000],
    },
    ctr: {
      down: [
        ["SR-007", 0.024, 0.021, -9_000, RO, 1310, 890],
        ["KD-030", 0.039, 0.037, -5_000, TK, 620, 580],
      ],
      up: [["SM-012", 0.03, 0.032, 4_000, RO, 2160, 3750]],
      closing: ["3 sản phẩm ít lượt bấm", -1_000, 2_000],
    },
    ctor: {
      down: [
        ["SM-012", 0.063, 0.054, -112_000, RO, 217, 162, [6_000, -118_000]],
        ["MN-015", 0.06, 0.054, -64_000, RO, 188, 151, [-4_000, -60_000]],
        ["KD-030", 0.051, 0.042, -58_000, RO, 140, 109, [-41_000, -17_000]],
        ["KC-004", 0.056, 0.05, -21_000, TK, 46, 38, [2_000, -23_000]],
        ["SR-007", 0.048, 0.046, -9_000, TK, 31, 27, [-3_000, -6_000]],
      ],
      up: [["TN-021", 0.061, 0.066, 28_000, RO, 98, 112, [20_000, 8_000]]],
      closing: ["2 sản phẩm ít đơn", -6_000, 12_000],
    },
    aov: {
      down: [
        ["TN-021", 182_000, 170_000, -48_000, RO, 98, 112],
        ["KD-030", 279_000, 268_000, -19_000, TK, 140, 109],
      ],
      up: [["SM-012", 149_000, 152_000, 6_000, TK, 217, 162]],
      closing: ["3 sản phẩm ít đơn", -3_000, -6_000],
    },
  },
  shop_tab: {
    impressions: {
      down: [
        ["MN-015", 420, 360, -14_000, RO, 12_600, 10_800],
        ["TN-021", 310, 290, -7_000, TK, 9_300, 8_700],
      ],
      up: [["SM-012", 380, 420, 9_000, TK, 11_400, 12_600]],
      closing: ["4 sản phẩm ít lượt hiển thị", -1_000, -1_000],
    },
    ctr: {
      down: [["KC-004", 0.052, 0.049, -3_000, TK, 410, 380]],
      up: [["SM-012", 0.061, 0.063, 2_000, TK, 700, 790]],
      closing: ["4 sản phẩm ít lượt bấm", 0, -1_000],
    },
    ctor: {
      down: [["KD-030", 0.066, 0.061, -6_000, TK, 52, 47]],
      up: [["TN-021", 0.07, 0.081, 21_000, RO, 64, 77]],
      closing: ["4 sản phẩm ít đơn", 1_000, 2_000],
    },
    aov: {
      down: [["TN-021", 186_000, 171_000, -22_000, RO, 64, 77]],
      up: [["MN-015", 128_000, 131_000, 3_000, TK, 52, 54]],
      closing: ["4 sản phẩm ít đơn", -2_000, -3_000],
    },
  },
};

const CONTENT_TABLES: Readonly<Record<"seller_video" | "seller_live", Partial<Record<CellMetric, TableSpec<ContentRow>>>>> = {
  seller_video: {
    impressions: {
      down: [],
      up: [["v2", "Review son lì 12 màu", "2026-09-21", ["SM-012"], 1370, 4880, 52_000, RO, 146_400]],
      closing: ["12 video ít lượt hiển thị", -2_000, -3_000],
    },
    ctr: {
      down: [
        ["v1", "Mặt nạ đất sét: trước và sau", "2026-09-02", ["MN-015"], 0.032, 0.019, -58_000, RO, 2240],
        ["v3", "Routine sáng 3 bước", "2026-09-15", ["SR-007", "TN-021", "SM-012"], 0.032, 0.026, -24_000, RO, 1660],
        ["v4", "Unbox toner rau má", "2026-09-28", ["TN-021"], 0.032, 0.029, -9_000, TK, 610],
      ],
      up: [],
      closing: ["12 video ít lượt bấm", -5_000, 1_000],
    },
  },
  seller_live: {
    impressions: {
      down: [],
      up: [["l2", "LIVE tối thứ Sáu", "2026-10-04", ["SM-012", "TN-021", "MN-015", "KD-030", "SR-007", "KC-004", "MN-015", "SM-012", "TN-021"], 5800, 9100, 30_000, RO, 9100]],
      closing: ["3 phiên LIVE ít lượt hiển thị", 2_000, 4_000],
    },
    ctr: {
      down: [],
      up: [["l3", "LIVE trưa", "2026-09-30", ["TN-021", "SM-012", "MN-015", "KD-030", "SR-007", "KC-004"], 0.047, 0.056, 9_000, TK, 410]],
      closing: ["3 phiên LIVE ít lượt bấm", 1_000, 1_000],
    },
    ctor: {
      down: [
        ["l1", "LIVE xả kho", "2026-09-27", ["KD-030", "MN-015", "SR-007"], 0.075, 0.059, -18_000, RO, 61],
        ["l4", "LIVE sáng", "2026-10-05", ["SM-012", "TN-021"], 0.075, 0.07, -3_000, TK, 12],
      ],
      up: [],
      closing: ["3 phiên LIVE ít đơn", -1_000, 0],
    },
  },
};

/** The sample's stored rankings, keyed like the endpoint's query (`stream` × `metric`). */
export function sampleRankings(): Partial<Record<RankedStream, Partial<Record<RankedMetric, RankingEnvelope>>>> {
  const out: Partial<Record<RankedStream, Partial<Record<RankedMetric, RankingEnvelope>>>> = {};
  for (const stream of ["product_card", "shop_tab"] as const) {
    out[stream] = {};
    for (const metric of ORDER) {
      const t = PRODUCT_TABLES[stream][metric];
      out[stream]![metric] = envelope(stream, metric, "product", t.down.map(productRow), t.up.map(productRow), t.closing);
    }
  }
  for (const stream of ["seller_video", "seller_live"] as const) {
    out[stream] = {};
    const kind: RowKind = stream === "seller_video" ? "video" : "live_session";
    for (const metric of ORDER) {
      const t = CONTENT_TABLES[stream][metric];
      if (!t) continue;
      const map = contentRow(stream);
      out[stream]![metric] = envelope(stream, metric, kind, t.down.map(map), t.up.map(map), t.closing);
    }
  }
  return out;
}
