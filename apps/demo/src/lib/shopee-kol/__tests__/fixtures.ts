import { versionOf, voucherCard } from "../../shopee-decisions/__tests__/fixtures";
import type { Card, CardDetail } from "../../shopee-decisions/types";
import type { KolApi, KolCert, KolReport, KolRow, KolSamplesApi, KolSamplesOverview, KolSamplesPreview } from "../types";

/** Synthetic KOLs ("KOL mẫu A" …): invented handles and numbers, no creator data. */

export function row(over: Partial<KolRow> = {}): KolRow {
  return {
    kol_key: "k1",
    handle: "KOL mẫu A",
    channel: "Shopee Video",
    product_id: "GT-A",
    product_name: "Găng tay cao su A",
    orders: 9,
    units: 14,
    gmv: 1_246_000,
    clicks: 310,
    conversion: 0.029,
    commission: 99_700,
    net_profit: 285_000,
    sample_cost: 172_000,
    profit_after_samples: 113_000,
    roi_with_samples: 0.42,
    roi_shopee: "9,8",
    payback_orders: 6,
    few_data: true,
    card: { id: "card-kol-1", code: "JC-2611-0016", kind: "affiliate_sample" },
    ...over,
  };
}

export const REPORT: KolReport = {
  window: { from: "2026-10-04", to: "2026-11-02", days: 30 },
  channels: ["Shopee Video", "Facebook", "TikTok"],
  product_rates: { "GT-A": 0.08, "TR-B": 0.1 },
  rows: [
    row(),
    row({ kol_key: "k2", handle: "KOL mẫu B", channel: "Facebook", product_id: "TR-B", product_name: "Túi rác sinh học B", orders: 12, units: 24, gmv: 1_416_000, clicks: 380, conversion: 0.032, commission: 141_600, net_profit: 160_000, sample_cost: 0, profit_after_samples: 160_000, roi_with_samples: 1.13, roi_shopee: "6,2", payback_orders: null, few_data: false, card: null }),
    row({ kol_key: "k3", handle: "KOL mẫu C", channel: "TikTok", orders: 3, units: 6, gmv: 534_000, clicks: 150, conversion: 0.02, commission: 42_700, net_profit: 40_000, sample_cost: 190_000, profit_after_samples: -150_000, roi_with_samples: -0.64, roi_shopee: "5,1", payback_orders: 14, card: { id: "card-kol-3", code: "JC-2611-0018", kind: "affiliate_invite" } }),
  ],
};

export function fakeKol(report: KolReport = REPORT): KolApi & { readonly calls: string[] } {
  const calls: string[] = [];
  return { calls, report: async () => (calls.push("report"), report) };
}

// ── The card ────────────────────────────────────────────────────────────────

export function cert(over: Partial<KolCert> = {}): KolCert {
  return {
    kol: { key: "k1", handle: "KOL mẫu A", channel: "Shopee Video" },
    invite: false,
    product_id: "GT-A",
    product_name: "Găng tay cao su A",
    qty: 3,
    commission_pct: 8,
    current_commission_pct: 8,
    sample: { unit_cost: 49_000, ship: 25_000, cost: 172_000 },
    expected: {
      orders: { p10: 1, p90: 7 },
      net: { p10: 60_000, p90: 420_000 },
      profit_after_samples: { p10: -112_000, p90: 248_000 },
      roi: { p10: -0.4, p90: 0.9 },
      payback_orders: 4,
      net_per_order: 42_000,
      commission_per_order: 10_000,
    },
    few_data: true,
    basis: "KOL 14 đơn / 310 lượt nhấp, riêng sản phẩm này 9 đơn",
    product_options: [
      { product_id: "GT-A", name: "Găng tay cao su A", commission_pct: 8 },
      { product_id: "TR-B", name: "Túi rác sinh học B", commission_pct: 10 },
    ],
    ...over,
  };
}

export function kolCard(invite = false): Card {
  const base = voucherCard({
    id: "card-kol-1",
    code: invite ? "JC-2611-0019" : "JC-2611-0016",
    product_queue: 9,
    family: "affiliate",
    family_label: "Tiếp thị liên kết",
    change_kind: invite ? "affiliate_invite" : "affiliate_sample",
    title: invite ? "Mời KOL “KOL mẫu D”" : "Gửi mẫu cho “KOL mẫu A”",
    inputs: { product_id: "GT-A", qty: invite ? 0 : 3, commission_pct: 8 },
    whatif: { sliders: [{ key: "commission_pct", label: "Hoa hồng", unit: "pct", min: 5, max: 20, step: 1, default: 8 }] },
    certain: { label: "Chắc chắn", kol: cert({ invite, qty: invite ? null : 3, sample: invite ? { unit_cost: null, ship: null, cost: 0 } : cert().sample, expected: { ...cert().expected, payback_orders: invite ? null : 4 } }) } as Card["certain"],
  });
  const v2 = voucherCard({ ...base, certain: { label: "Chắc chắn", kol: cert({ invite, qty: invite ? null : 2, product_id: "TR-B", product_name: "Túi rác sinh học B", commission_pct: 10, sample: invite ? { unit_cost: null, ship: null, cost: 0 } : { unit_cost: 31_000, ship: 25_000, cost: 87_000 } }) } as Card["certain"] });
  return {
    ...base,
    versions: [versionOf(base, 1, invite ? "Mời bán Găng tay cao su A, hoa hồng 8%" : "Gửi 3 mẫu Găng tay cao su A"), versionOf(v2, 2, invite ? "Mời bán Túi rác sinh học B, hoa hồng 10%" : "Gửi 2 mẫu Túi rác sinh học B")],
  };
}

export function kolDetail(invite = false, over: Partial<CardDetail> = {}): CardDetail {
  const card = kolCard(invite);
  return { id: "card-kol-1", code: card.code ?? null, product_id: "GT-A", product_queue: 9, status: "sent", family: "affiliate", family_label: "Tiếp thị liên kết", change_kind: card.change_kind, title: card.title, reason: "KOL này bán được 9 đơn Găng tay cao su A.", section: "lien_ket", metric: card.metric, scope: card.scope, rank: { position: 9 }, certain_summary: { dprofit_month: 0, dgmv_month: 0 }, predicted_summary: { dgmv_month: { p10: 0, p50: 0, p90: 0 }, dprofit_month: { p10: 0, p50: 0, p90: 0 }, label: "Dự kiến", effect_days: 30 }, floor_ok: true, plan: "Kết quả sau 14 ngày", stale: false, bundle: false, sent_at: null, card, journey: [], ...over };
}

// ── Mẫu KOL sheet ───────────────────────────────────────────────────────────

export const OVERVIEW: KolSamplesOverview = {
  version: 3,
  filename: "mau-kol-2611.xlsx",
  reasons: [],
  rows: [
    { kol: "KOL mẫu A", product: "GT-A · Găng tay cao su A", qty: 3, sent_on: "28/10/2026", ship: 25_000 },
    { kol: "KOL mẫu B", product: "TR-B · Túi rác sinh học B", qty: 2, sent_on: "30/10/2026", ship: 25_000 },
    { kol: "KOL mẫu C", product: "MR-C · Miếng rửa chén C", qty: 0, sent_on: null, ship: 25_000 },
  ],
};

export const PREVIEW: KolSamplesPreview = {
  file_hash: "h1",
  current_version: 3,
  rows_valid: 2,
  rows_rejected: 1,
  checks: [
    { row: 2, kol: "KOL mẫu A", product: "GT-A", ok: true, message: "Hợp lệ" },
    { row: 3, kol: "KOL mẫu C", product: "GT-A", ok: true, message: "Hợp lệ" },
    { row: 5, kol: "KOL mẫu AA", product: "GT-A", ok: false, message: "Không tìm thấy KOL này trong đơn Tiếp thị liên kết. Ý bạn là “KOL mẫu A”?" },
  ],
  diffs: [
    { kol: "KOL mẫu A", product_name: "Găng tay cao su A", tag: "Đổi", cells: [{ label: "Số lượng mẫu", old: "3", new: "4" }, { label: "Chi phí mẫu", old: "172.000đ", new: "221.000đ" }], consequence: "Chi phí mẫu +49.000đ. Hoàn vốn: ≥ 6 đơn → ≥ 8 đơn. Cặp KOL × sản phẩm dưới 10 đơn (ít dữ liệu): ROI chỉ để tham khảo." },
    { kol: "KOL mẫu E", product_name: "Túi rác sinh học B", tag: "Thêm mới", cells: [{ label: "Số lượng mẫu", old: "0", new: "2" }], consequence: "Chi phí mẫu +87.000đ." },
  ],
  cards_recalculated: ["JC-2611-0016", "JC-2611-0017"],
};

export function fakeSamples(over: Partial<{ overview: KolSamplesOverview; preview: KolSamplesPreview; fail: Partial<Record<keyof KolSamplesApi, Error>> }> = {}): KolSamplesApi & { readonly calls: { name: string; args: unknown[] }[] } {
  const calls: { name: string; args: unknown[] }[] = [];
  const run = <T,>(name: keyof KolSamplesApi, value: T, ...args: unknown[]): Promise<T> => {
    calls.push({ name, args });
    const err = over.fail?.[name];
    return err ? Promise.reject(err) : Promise.resolve(value);
  };
  return {
    calls,
    overview: () => run("overview", over.overview ?? OVERVIEW),
    template: () => run("template", { blob: new Blob(["x"]), filename: "mau-kol.xlsx" }),
    preview: (f) => run("preview", over.preview ?? PREVIEW, f),
    apply: (f, reason, hash) => run("apply", { version: 4, cards_recalculated: ["JC-2611-0016", "JC-2611-0017"] }, f, reason, hash),
  };
}
