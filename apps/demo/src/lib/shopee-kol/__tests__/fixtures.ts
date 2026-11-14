import type { ApplyResult, ImportPreview, InputsOverview, ShopInputsApi } from "../../shop-inputs/types";
import { versionOf, voucherCard } from "../../shopee-decisions/__tests__/fixtures";
import type { Card, CardDetail } from "../../shopee-decisions/types";
import type { KolApi, KolBlock, KolProductReport, KolQuery, KolReport, KolRow } from "../types";

/** Synthetic KOLs ("KOL mẫu A" …): invented handles and numbers, no creator data. Shapes are the backend's (`kol.table`). */

export function row(over: Partial<KolRow> = {}): KolRow {
  return {
    kol_key: "k1",
    handle: "KOL mẫu A",
    channel: "Shopee Video",
    item_id: "GT-A",
    product_name: "Găng tay cao su A",
    orders: 9,
    units: 14,
    gmv: 1_246_000,
    clicks: null,
    kol_clicks: 310,
    kol_conversion: 0.029,
    commission: 99_700,
    commission_rate: 0.08,
    commission_sources: { export: 9 },
    net_profit: 285_000,
    profit_orders: 9,
    unknown_lines: 0,
    sample_qty: 3,
    sample_cost: 172_000,
    sample_cost_basis: "giá vốn thực",
    profit_after_samples: 113_000,
    roi_incl_samples: 0.42,
    roi_shopee: 9.8,
    payback_orders: 6,
    pair_orders: 9,
    low_data: true,
    low_data_label: "Ít dữ liệu",
    mcn: null,
    campaign_type: null,
    card: { id: "card-kol-1", code: "JC-2611-0016", change_kind: "affiliate_sample", kind_label: "Gửi mẫu", title: "Gửi mẫu cho “KOL mẫu A”", product_queue: 9, item_id: "GT-A" },
    ...over,
  };
}

export const ROWS: readonly KolRow[] = [
  row(),
  row({ kol_key: "k2", handle: "KOL mẫu B", channel: "Facebook", item_id: "TR-B", product_name: "Túi rác sinh học B", orders: 12, units: 24, gmv: 1_416_000, kol_clicks: 380, kol_conversion: 0.032, commission: 141_600, net_profit: 160_000, sample_qty: 0, sample_cost: 0, profit_after_samples: 160_000, roi_incl_samples: 1.13, roi_shopee: 6.2, payback_orders: null, pair_orders: 12, low_data: false, low_data_label: null, card: null }),
  row({ kol_key: "k3", handle: "KOL mẫu C", channel: "TikTok", orders: 3, units: 6, gmv: 534_000, kol_clicks: 150, kol_conversion: 0.02, commission: 42_700, net_profit: 40_000, sample_qty: 4, sample_cost: 190_000, profit_after_samples: -150_000, roi_incl_samples: -0.64, roi_shopee: 5.1, payback_orders: 14, pair_orders: 3, card: { id: "card-kol-3", code: "JC-2611-0018", change_kind: "affiliate_invite", kind_label: "Mời KOL", title: "Mời KOL “KOL mẫu C”", product_queue: 3, item_id: "GT-A" } }),
];

/** What `kol.table` answers for the rows that survive the filters: totals of those rows, filters from ALL rows. */
export function reportOf(all: readonly KolRow[], q: KolQuery = {}): KolReport {
  const keep = all.filter((r) => (!q.channel || r.channel === q.channel) && (!q.itemId || r.item_id === q.itemId));
  const sum = (f: (r: KolRow) => number) => keep.reduce((a, r) => a + f(r), 0);
  const comm = sum((r) => r.commission);
  const net = sum((r) => r.net_profit);
  const sample = sum((r) => r.sample_cost ?? 0);
  const roi = comm + sample > 0 ? (net - sample) / (comm + sample) : null;
  return {
    window: { start: "2026-10-04", end: "2026-11-02", days: 30 },
    rows: keep,
    totals: { rows: keep.length, kols: new Set(keep.map((r) => r.kol_key)).size, orders: sum((r) => r.orders), units: sum((r) => r.units), gmv: sum((r) => r.gmv), commission: comm, net_profit: net, sample_cost: sample, profit_after_samples: net - sample, roi_incl_samples: roi },
    filters: {
      channels: [...new Set(all.map((r) => r.channel))].sort(),
      channel_options: [...new Map(all.map((r) => [r.channel, r.channel_label ?? r.channel])).entries()].map(([value, label]) => ({ value, label })),
      products: [...new Map(all.map((r) => [r.item_id, r.product_name])).entries()].map(([item_id, name]) => ({ item_id, name })),
      kols: [...new Map(all.map((r) => [r.kol_key, r.handle])).entries()].map(([kol_key, handle]) => ({ kol_key, handle })),
    },
    applied: { channel: q.channel ?? null, item_id: q.itemId ?? null, kol: q.kol ?? null, sort: q.sort ?? "net_profit" },
    labels: {
      roi_self: "ROI gồm mẫu",
      roi_shopee: "ROI Shopee (chỉ hoa hồng)",
      low_data: "Ít dữ liệu",
      roi_formula: "(lợi nhuận ròng − chi phí mẫu) ÷ (hoa hồng + chi phí mẫu)",
      roi_shopee_note: "Giá trị ROI trong file xuất KOL của Shopee, giữ nguyên, không tính lại; chỉ tính hoa hồng.",
      sample_cost: "số lượng × (giá vốn + đóng gói) + phí ship; không tính phí book KOL",
      commission: "tính theo mức hoa hồng áp dụng cho từng sản phẩm bán ra",
      low_data_threshold: 10,
    },
    data_quality: { untagged_affiliate_lines: 0, lines_without_commission: 0, partner_export: null },
    order_basis: { key: "confirmed", label: "Đơn đã xác nhận" },
  };
}

export const REPORT: KolReport = reportOf(ROWS);

export function productReportOf(all: readonly KolRow[], itemId: string): KolProductReport {
  return { ...reportOf(all, { itemId }), product: { item_id: itemId, name: all.find((r) => r.item_id === itemId)?.product_name ?? null, commission_rate: 0.08, commission_rate_source: "export", affiliate_orders: 12 } };
}

export function fakeKol(rows: readonly KolRow[] = ROWS): KolApi & { readonly calls: { name: string; args: unknown[] }[] } {
  const calls: { name: string; args: unknown[] }[] = [];
  return {
    calls,
    report: async (q) => (calls.push({ name: "report", args: [q] }), reportOf(rows, q)),
    productReport: async (itemId, w) => (calls.push({ name: "productReport", args: [itemId, w] }), productReportOf(rows, itemId)),
  };
}

// ── The card ────────────────────────────────────────────────────────────────

const SAMPLE = { cost: 172_000, unit_cogs: 40_000, unit_packaging: 9_000, ship_fee: 25_000, ship_source: "kol", cogs_source: "real", label: "giá vốn thực" } as const;

/** The `kol` block of a version (`kol_cards.build_kol_card`). */
export function block(over: Partial<KolBlock> = {}): KolBlock {
  return {
    kol_key: "k1",
    handle: "KOL mẫu A",
    channel: "Shopee Video",
    invite: false,
    roi_shopee: 9.8,
    product: { item_id: "GT-A", name: "Găng tay cao su A" },
    qty: 3,
    commission_pct: 8,
    commission_pct_current: 8,
    commission_source: "export",
    sample: SAMPLE,
    expected: {
      orders: { p10: 1, p50: 3.5, p90: 7 },
      gmv: 480_000,
      commission: 38_400,
      net_profit: 150_000,
      profit_after_sample: -22_000,
      profit_after_sample_range: [-112_000, 248_000],
      roi_incl_samples: -0.1,
      payback_orders: 4,
      net_per_order: 42_000,
    },
    low_data: true,
    low_data_label: "Ít dữ liệu",
    pair_orders: 9,
    orders_threshold: 10,
    shrinkage: {},
    choices: [
      { value: "GT-A", label: "Găng tay cao su A", orders_p50: 3.5, profit_p50: -22_000, selected: true },
      { value: "TR-B", label: "Túi rác sinh học B", orders_p50: 2.1, profit_p50: -40_000, selected: false },
    ],
    measurement: { kind: "kol_pair", metric: "orders", kol_key: "k1", item_id: "GT-A", send_date: null, baseline_days: 28, note: "Đo đơn của cặp KOL × sản phẩm, trước và sau ngày gửi." },
    ...over,
  };
}

const INVITE_SAMPLE = null;

export function kolCard(invite = false): Card {
  const v1 = block({ invite, qty: invite ? 0 : 3, sample: invite ? INVITE_SAMPLE : SAMPLE, expected: { ...block().expected, payback_orders: invite ? null : 4 } });
  const v2 = block({
    invite,
    qty: invite ? 0 : 2,
    product: { item_id: "TR-B", name: "Túi rác sinh học B" },
    commission_pct: 10,
    sample: invite ? INVITE_SAMPLE : { ...SAMPLE, cost: 87_000, unit_cogs: 25_000, unit_packaging: 6_000 },
    expected: { ...block().expected, orders: { p10: 0.6, p50: 2.1, p90: 4.6 }, profit_after_sample_range: [-80_000, 120_000] },
    choices: [
      { value: "GT-A", label: "Găng tay cao su A", orders_p50: 3.5, profit_p50: -22_000, selected: false },
      { value: "TR-B", label: "Túi rác sinh học B", orders_p50: 2.1, profit_p50: -40_000, selected: true },
    ],
  });
  const base = voucherCard({
    id: "card-kol-1",
    code: invite ? "JC-2611-0019" : "JC-2611-0016",
    product_queue: 9,
    family: "affiliate",
    family_label: "Tiếp thị liên kết",
    change_kind: invite ? "affiliate_invite" : "affiliate_sample",
    title: invite ? "Mời KOL — KOL mẫu D · Găng tay cao su A" : "Gửi mẫu cho KOL — KOL mẫu A · Găng tay cao su A",
    inputs: invite ? { item_id: "GT-A", commission_pct: 8 } : { item_id: "GT-A", qty: 3, commission_pct: 8 },
    whatif: { sliders: [...(invite ? [] : [{ key: "qty", label: "Số lượng mẫu", unit: "count", min: 1, max: 50, step: 1, default: 3 }]), { key: "commission_pct", label: "Hoa hồng cho KOL", unit: "pct", min: 0, max: 50, step: 0.5, default: 8 }] },
    certain: { label: "Chắc chắn", kind: "kol", note: "Phần chắc chắn chỉ có chi phí mẫu; đơn và lợi nhuận từ KOL là phần dự kiến." } as unknown as Card["certain"],
    kol: v1,
  });
  const second = voucherCard({ ...base, inputs: { ...base.inputs, item_id: "TR-B", commission_pct: 10 }, kol: v2 });
  return {
    ...base,
    versions: [
      versionOf(base, 1, invite ? "Mặc định của Juli" : "Mặc định của Juli", { kol: v1 }),
      versionOf(second, 2, "Sản phẩm: Túi rác sinh học B", { kol: v2 }),
    ],
  };
}

export function kolDetail(invite = false, over: Partial<CardDetail> = {}): CardDetail {
  const card = kolCard(invite);
  return { id: "card-kol-1", code: card.code ?? null, product_id: "GT-A", product_queue: 9, status: "sent", family: "affiliate", family_label: "Tiếp thị liên kết", change_kind: card.change_kind, title: card.title, reason: "KOL này bán được 9 đơn Găng tay cao su A.", section: "lien_ket", metric: card.metric, scope: card.scope, rank: { position: 9 }, predicted_summary: { dgmv_month: { p10: 0, p50: 0, p90: 0 }, dprofit_month: { p10: 0, p50: 0, p90: 0 }, label: "Dự kiến", effect_days: 30 }, floor_ok: true, plan: "Kết quả sau 14 ngày", stale: false, bundle: false, sent_at: null, card, journey: [], ...over };
}

// ── Mẫu KOL sheet (the shop-inputs routes: the same workbook as the SKU sheet) ──

const EMPTY_AFFECTED = { total: 0, proposals: 0, action_cards: 0, item_ids: [], shop_wide: false } as const;

export const OVERVIEW: InputsOverview = {
  samples: {
    pairs: 2,
    shipments: 3,
    items: [
      { scope_ref: "kol:k1:GT-A", kol_key: "k1", handle: "KOL mẫu A", item_id: "GT-A", sku: "GT-A", shipments: [{ handle: "KOL mẫu A", qty: 3, sent_on: "2026-10-28", ship_fee: 25_000 }], sample_cost: 172_000, cost_label: "giá vốn thực" },
      { scope_ref: "kol:k2:TR-B", kol_key: "k2", handle: "KOL mẫu B", item_id: "TR-B", sku: "TR-B", shipments: [{ handle: "KOL mẫu B", qty: 2, sent_on: "2026-10-30", ship_fee: 25_000 }, { handle: "KOL mẫu B", qty: 1, sent_on: "2026-11-01", ship_fee: 0 }], sample_cost: 87_000, cost_label: "giá vốn giả định" },
    ],
  },
  catalogue: { sku_rows: 42, items: 12, with_cost: 30 },
  cost_fallback: { count: 0, assumed_share: "1/3", margin_pct: 66.7, source: "assumed_one_third", skus: [] },
  months: [],
  reasons: [],
};

export const PREVIEW: ImportPreview = {
  file_hash: "h1",
  counts: { sku_rows: 0, sku_rows_valid: 0, sku_rows_rejected: 0, sku_rows_unchanged: 0, sample_rows: 3, sample_rows_valid: 2, sample_rows_rejected: 1, sample_rows_unchanged: 0, samples_changed: 2, goal_rows: 0, goal_rows_rejected: 0, changes: 2, skus_changed: 0, months_changed: 0 },
  rejections: [{ sheet: "Mẫu KOL", row: 5, sku: "KOL mẫu AA", column: "Sản phẩm", value: "XX-9", reason: "Không có mã sản phẩm hoặc SKU này trong shop.", kind: "unknown_sku", kind_label: "SKU lạ" }],
  diffs: [],
  goal_diffs: [],
  sample_diffs: [
    { scope_ref: "kol:k1:GT-A", kol_key: "k1", handle: "KOL mẫu A", item_id: "GT-A", sku: "GT-A", tag: "Đổi", old: [{ handle: "KOL mẫu A", qty: 3, sent_on: "2026-10-28", ship_fee: 25_000 }], new: [{ handle: "KOL mẫu A", qty: 4, sent_on: "2026-10-28", ship_fee: 25_000 }], old_cost: 172_000, new_cost: 221_000, cost_label: "giá vốn thực", effect: "Chi phí mẫu 172.000đ → 221.000đ (giá vốn thực)" },
    { scope_ref: "kol:k5:TR-B", kol_key: "k5", handle: "KOL mẫu E", item_id: "TR-B", sku: "TR-B", tag: "Mới", old: [], new: [{ handle: "KOL mẫu E", qty: 2, sent_on: "2026-11-02", ship_fee: 0 }], old_cost: null, new_cost: 87_000, cost_label: "giá vốn giả định", effect: "Chi phí mẫu (chưa có giá vốn) → 87.000đ (giá vốn giả định)" },
  ],
  warnings: [],
  affected: { total: 2, proposals: 2, action_cards: 0, item_ids: ["GT-A", "TR-B"], shop_wide: false },
};

type SheetApi = Pick<ShopInputsApi, "overview" | "template" | "preview" | "apply">;

export function fakeSamples(over: Partial<{ overview: InputsOverview; preview: ImportPreview; fail: Partial<Record<keyof SheetApi, Error>> }> = {}): ShopInputsApi & { readonly calls: { name: string; args: unknown[] }[] } {
  const calls: { name: string; args: unknown[] }[] = [];
  const run = <T,>(name: keyof SheetApi, value: T, ...args: unknown[]): Promise<T> => {
    calls.push({ name, args });
    const err = over.fail?.[name];
    return err ? Promise.reject(err) : Promise.resolve(value);
  };
  const applied: ApplyResult = { file_hash: "h1", reason: "", applied_at: "2026-11-03T10:00:00", versions_written: 2, skus_changed: 0, samples_changed: 2, months_changed: 0, rejected: 1, affected: { ...EMPTY_AFFECTED, total: 2, proposals: 2, item_ids: ["GT-A", "TR-B"] } };
  return {
    calls,
    overview: () => run("overview", over.overview ?? OVERVIEW),
    template: () => run("template", { blob: new Blob(["x"]), filename: "thong-so-mau.xlsx", skuRows: 42 }),
    preview: (f) => run("preview", over.preview ?? PREVIEW, f),
    apply: (f, reason, hash) => run("apply", { ...applied, reason }, f, reason, hash),
    versionsIndex: async () => [],
    versions: () => Promise.reject(new Error("not used")),
    restore: () => Promise.reject(new Error("not used")),
  };
}
