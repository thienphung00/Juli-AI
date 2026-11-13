import { five } from "../../shopee-analytics/__tests__/fixtures";
import type { RecoApi } from "../client";
import type {
  ExecutionStates,
  MeasurementStates,
  Card,
  CardByCode,
  CardDetail,
  CardList,
  CardSummary,
  CardVersion,
  CompareResult,
  ExecutionSheet,
  FloorBreach,
  JourneyEvent,
  ManualResult,
  MegaChild,
  MoneyAt,
  VersionBrief,
  VersionStatus,
} from "../types";

/**
 * Synthetic cards in the shape of `services/shopee_recommendations` (household-goods shop of the
 * artboards; invented numbers, no shop data). The voucher card is the worked example of
 * `CardWhatIf.dc.html`: SKU BEP-S5-CB with the absolute floor 121.176đ and the operating floor
 * 181.979đ, voucher A (10.000đ for orders from 200.000đ) -> C (15.000đ from 299.000đ), where the
 * extra spend breaks even at 3 extra orders.
 */

export const SHEET_VOUCHER: ExecutionSheet = {
  page: { label: "Marketing › Voucher của tôi", path: "/portal/marketing/vouchers/list", verified: true, deep_link: "https://banhang.shopee.vn/portal/marketing/vouchers/list", button: "Mở trang để sửa" },
  steps: [
    { order: 1, field: "Giá trị giảm (VND)", before: 10000, after: 15000, unit: "VND", copy: "15000" },
    { order: 2, field: "Đơn tối thiểu", before: 200000, after: 299000, unit: "VND", copy: "299000" },
    { order: 3, field: "Số lượng voucher", before: 50, after: 50, unit: "cái", copy: "50" },
    { order: 4, field: "Thời gian áp dụng", before: null, after: "30 ngày", unit: null, copy: "30 ngày" },
  ],
  time_window: { start: "khi bạn bấm lưu", days: 30 },
  changes: [{ change_kind: "voucher", target: { voucher_id: null }, expected: { discount_amount: 15000, min_spend: 299000, usage_limit: 50 } }],
  save_hint: "Bấm nút Lưu / Áp dụng / Xác nhận của chính Shopee; Juli không bấm thay bạn.",
  revert_steps: [
    { order: 1, field: "Giá trị giảm (VND)", before: 15000, after: 10000, unit: "VND", copy: "10000" },
    { order: 2, field: "Đơn tối thiểu", before: 299000, after: 200000, unit: "VND", copy: "200000" },
  ],
  readback: { kinds: ["voucher"], deadline_hours: 48, note: "Connector đọc lại ở lần chạy kế tiếp." },
};

export const OPERATING_BREACH: FloorBreach = { sku: "BEP-S5-CB", kind: "operating", floor: 181979, min_unit_price: 175000, lines: 30 };
export const ABSOLUTE_BREACH: FloorBreach = { sku: "BEP-S5-CB", kind: "absolute", floor: 121176, min_unit_price: 110000, lines: 12 };

const at = (dgmv: number, dorders: number | null, dprofit: number | null): MoneyAt => ({ dgmv, dorders, dprofit });

export function voucherCard(p: Partial<Card> = {}): Card {
  return {
    id: "card-voucher",
    family: "voucher",
    family_label: "Voucher",
    change_kind: "min_spend_voucher",
    title: "Voucher đơn tối thiểu — Bộ vệ sinh bếp 5 món · Cơ bản",
    reason: "Giỏ hàng trung bình 241.000đ, nhiều đơn dừng ngay dưới 299.000đ.",
    as_of: "2026-11-02",
    window: { from: "2026-10-04", to: "2026-11-02", days: 30 },
    order_basis: { key: "confirmed", label: "Đơn đã xác nhận" },
    metric: { key: "aov", critical_id: "BEP-S5", critical_kpi: "aov", flow: "the_san_pham_khac", at_stake_per_day: 120000 },
    scope: { level: "shop", product_ids: ["BEP-S5"], sku_ids: ["BEP-S5-CB"], campaign_key: null },
    change: {
      change_kind: "min_spend_voucher",
      target: { voucher_id: null },
      before: { value: 10000, min_spend: 200000, quantity: 50, label: "voucher hiện tại" },
      after: { value: 15000, min_spend: 299000, quantity: 50, days: 30 },
    },
    inputs: { value: 15000, pct: null, max_value: null, min_spend: 299000, quantity: 50, days: 30, per_user_limit: 2 },
    whatif: {
      sliders: [
        { key: "value", label: "Giá trị voucher", unit: "vnd", min: 1000, max: 500000, step: 1000, default: 15000 },
        { key: "min_spend", label: "Đơn tối thiểu", unit: "vnd", min: 0, max: 5000000, step: 10000, default: 299000 },
        { key: "quantity", label: "Số lượng voucher", unit: "count", min: 1, max: 100000, step: 1, default: 50 },
        { key: "days", label: "Số ngày", unit: "days", min: 1, max: 90, step: 1, default: 30 },
      ],
    },
    certain: {
      label: "Chắc chắn",
      kind: "voucher",
      qualifying_orders: 12,
      total_orders: 30,
      days: 30,
      extra_cost: 63000,
      break_even_extra_orders: 3,
      ad_margin_below_target: false,
      organic: { orders: 21, profit_per_order: 24000, contribution_per_order: 31000 },
      ad_attributed: { orders: 9, profit_per_order: 15000, contribution_per_order: 20000 },
      predicted_net: { net_profit_low: -30000, net_profit_high: 210000, extra_revenue_per_extra_spend_low: 1.4, extra_revenue_per_extra_spend_high: 3.2 },
    },
    five_numbers: five({
      discount: { vnd_before: 300000, vnd_after: 363000, pct_before: 4.2, pct_after: 5.0 },
      margin: { profit_before: 1_345_000, profit_after: 1_282_000, pct_before: 26.9, pct_after: 25.6, is_partial: false, cost_coverage_pct: 100 },
      orders: { before: 30, after: 30, change_pct: 0 },
      aov: { before: 241000, after: 241000, change_pct: 0 },
      extra_revenue_per_extra_spend: { extra_revenue: null, extra_spend: 63000, per_vnd: null, pct: null, status: "needs_volume", below_one: false },
    }),
    floor: { breaches: [], unknown_skus: [], ok: true },
    spend: { shop_chi_per_day_now: 1_110_211, card_dchi_per_day: 2100, shop_chi_per_day_after: 1_112_311, cap: 1_200_000, over_cap: false },
    predicted: {
      label: "Dự kiến",
      money_per_month: {
        days: 30,
        certain: { dgmv: 0, dprofit: -63000, dchi: 63000 },
        predicted: { p10: at(200000, 1, 20000), p50: at(600000, 2, 120000), p90: at(1_400_000, 6, 300000) },
        total: { p10: at(200000, 1, -43000), p50: at(600000, 2, 57000), p90: at(1_400_000, 6, 237000) },
      },
    },
    measurement_plan: { metric: "aov", planned_days: 14, label: "Kết quả sau 14 ngày" },
    execution_sheet: SHEET_VOUCHER,
    bundle: false,
    ...p,
  };
}

/** Voucher B of the artboard: 15.000đ from 200.000đ, a thinner margin and a bigger spend. */
export function voucherCardB(): Card {
  return voucherCard({
    inputs: { value: 15000, pct: null, max_value: null, min_spend: 200000, quantity: 50, days: 30, per_user_limit: 2 },
    five_numbers: five({
      discount: { vnd_before: 300000, vnd_after: 520000, pct_before: 4.2, pct_after: 7.1 },
      margin: { profit_before: 1_345_000, profit_after: 1_190_000, pct_before: 26.9, pct_after: 23.4, is_partial: false, cost_coverage_pct: 100 },
      orders: { before: 30, after: 30, change_pct: 0 },
      aov: { before: 241000, after: 241000, change_pct: 0 },
      extra_revenue_per_extra_spend: { extra_revenue: null, extra_spend: 155000, per_vnd: null, pct: null, status: "needs_volume", below_one: false },
    }),
    certain: { ...voucherCard().certain, extra_cost: 155000, break_even_extra_orders: 7 },
  });
}

export function breachedVoucherCard(breaches: readonly FloorBreach[] = [OPERATING_BREACH]): Card {
  return voucherCard({ inputs: { ...voucherCard().inputs, value: 25000 }, floor: { breaches, unknown_skus: [], ok: false } });
}

export function summaryOf(card: Card, p: Partial<CardSummary> = {}): CardSummary {
  const pm = card.predicted.money_per_month;
  return {
    id: card.id ?? "card-voucher",
    code: card.code ?? null,
    product_id: card.scope.product_ids[0] ?? null,
    product_queue: card.product_queue ?? 1,
    product_measuring: null,
    versions: (card.versions ?? []).map(briefOf),
    origin: card.origin ?? null,
    status: "sent",
    cycle: 1,
    family: card.family,
    family_label: card.family_label,
    change_kind: card.change_kind,
    title: card.title,
    reason: card.reason,
    section: "aov",
    metric: card.metric,
    scope: card.scope,
    rank: { position: 1 },
    certain_summary: { dprofit_month: pm.certain.dprofit, dgmv_month: pm.certain.dgmv },
    predicted_summary: {
      dgmv_month: { p10: pm.predicted.p10.dgmv, p50: pm.predicted.p50.dgmv, p90: pm.predicted.p90.dgmv },
      dprofit_month: { p10: pm.total.p10.dprofit, p50: pm.total.p50.dprofit, p90: pm.total.p90.dprofit },
      label: "Dự kiến",
      effect_days: 30,
    },
    floor_ok: card.floor.ok,
    plan: card.measurement_plan.label,
    stale: false,
    bundle: card.bundle,
    sent_at: "2026-11-03T02:00:00Z",
    ...p,
  };
}

export function detailOf(card: Card, p: Partial<CardDetail> = {}): CardDetail {
  return { ...summaryOf(card), card, journey: [], ...p };
}

// ── Versions (P91 D-2) ──────────────────────────────────────────────────────

/** A card's evaluation as version `n` of the card. */
export function versionOf(card: Card, n: number, label: string, over: Partial<CardVersion> = {}): CardVersion {
  const status: VersionStatus = card.floor.ok ? "ok" : "floor_breach";
  return {
    version: n,
    code: card.code ? `${card.code}-V${n}` : null,
    label,
    status,
    default: n === 1,
    ranked: n === 1 && status === "ok",
    refusal: null,
    inputs: card.inputs,
    reason: card.reason,
    change: card.change,
    whatif: card.whatif,
    certain: card.certain,
    five_numbers: card.five_numbers,
    floor: card.floor,
    spend: card.spend,
    predicted: card.predicted,
    measurement_plan: card.measurement_plan,
    execution_sheet: card.execution_sheet,
    notes: card.notes,
    ...over,
  };
}

/** The worked example of `CardVersions.dc.html`: voucher V1 (299.000đ), V2 (200.000đ) and V3 that breaks the floor. */
export function versionedVoucher(p: Partial<Card> = {}): Card {
  const v1 = voucherCard({ code: "JC-2611-0007", product_queue: 1 });
  const v2 = voucherCardB();
  const v3 = breachedVoucherCard();
  return {
    ...v1,
    code: "JC-2611-0007",
    product_queue: 1,
    versions: [
      versionOf(v1, 1, "Mặc định của Juli"),
      versionOf({ ...v2, code: "JC-2611-0007" }, 2, "15.000đ cho đơn ≥ 200.000đ"),
      versionOf({ ...v3, code: "JC-2611-0007" }, 3, "25.000đ cho đơn ≥ 299.000đ"),
    ],
    ...p,
  };
}

export function titleCard(p: Partial<Card> = {}): Card {
  const base = voucherCard({
    id: "card-title",
    code: "JC-2611-0011",
    product_queue: 4,
    family: "listing",
    family_label: "Tên, từ khoá, ảnh bìa",
    change_kind: "title",
    title: 'Tiêu đề mới, từ khoá "găng tay cao su"',
    inputs: { title: "Găng Tay Cao Su Rửa Chén Chống Trượt Dày Dai Bền Size S M L Đa Năng Nhà Bếp Giặt Đồ Giá Rẻ Loại 1" },
    whatif: { sliders: [] },
    certain: { label: "Chắc chắn" },
    spend: null,
  });
  return {
    ...base,
    versions: [
      versionOf(base, 1, "Tiêu đề A"),
      versionOf({ ...base, inputs: { title: "Găng Tay Cao Su Rửa Chén Gia Dụng Dày Dai Chống Trượt Size S M L Cho Nhà Bếp Giặt Đồ Lau Dọn" } }, 2, "Tiêu đề B"),
    ],
    ...p,
  };
}

export function briefOf(v: CardVersion): VersionBrief {
  const pm = v.predicted?.money_per_month.total.p50;
  return { version: v.version, code: v.code, label: v.label, status: v.status, ranked: v.ranked, inputs: v.inputs, floor_ok: v.floor?.ok ?? null, dprofit_month_p50: pm?.dprofit ?? null, dgmv_month_p50: pm?.dgmv ?? null };
}

// ── Other families ──────────────────────────────────────────────────────────

export function adsCard(): Card {
  return voucherCard({
    id: "card-ads",
    family: "ads",
    family_label: "Quảng cáo",
    change_kind: "ads_budget",
    title: "Đổi ngân sách ngày — Chiến dịch Sản phẩm",
    metric: { key: "ads_gmv", critical_id: null, critical_kpi: "gmv", flow: null, at_stake_per_day: 80000 },
    inputs: { daily_budget: 300000 },
    whatif: { sliders: [{ key: "daily_budget", label: "Ngân sách / ngày", unit: "vnd", min: 0, max: 100000000, step: 10000, default: 300000 }] },
    certain: { label: "Chắc chắn" },
  });
}

export function promotionCard(): Card {
  return voucherCard({
    id: "card-promo",
    family: "promotion",
    family_label: "Khuyến mãi / giá",
    change_kind: "product_discount",
    title: "Giảm giá sản phẩm — Bộ vệ sinh bếp 5 món",
    inputs: { discount_pct: 12 },
    whatif: { sliders: [{ key: "discount_pct", label: "Mức giảm", unit: "pct", min: 0, max: 60, step: 1, default: 12 }] },
    certain: { label: "Chắc chắn" },
  });
}

export function pauseCard(): Card {
  return voucherCard({ id: "card-pause", family: "ads", change_kind: "ads_pause", title: "Tạm dừng chiến dịch", inputs: {}, whatif: { sliders: [] }, certain: { label: "Chắc chắn" } });
}

// ── Mega sale ───────────────────────────────────────────────────────────────

const CHILD_PAGE = SHEET_VOUCHER.page;

export function megaChildren(): MegaChild[] {
  const base = { source_card_id: null, items: ["BEP-S5"], campaign_key: null, starts: "2026-11-11T00:00:00" };
  return [
    { ...base, child_id: "child-1", change_kind: "product_discount", family: "promotion", label: "Giảm giá sản phẩm", inputs: { discount_pct: 12 }, summary: { skus: [{ sku: "BEP-S5-CB", price: 199000 }] }, page: { ...CHILD_PAGE, label: "Marketing › Chương trình giảm giá", verified: true } },
    { ...base, child_id: "child-2", change_kind: "min_spend_voucher", family: "voucher", label: "Voucher đơn tối thiểu", inputs: { value: 15000 }, summary: { value: 15000, min_spend: 299000 }, page: CHILD_PAGE },
    { ...base, child_id: "child-3", change_kind: "ads_budget", family: "ads", label: "Đổi ngân sách ngày", inputs: { daily_budget: 400000 }, summary: { daily_budget: 400000 }, page: { ...CHILD_PAGE, label: "Marketing › Quảng cáo Shopee", verified: false, deep_link: null, path: null } },
  ];
}

export function megaCard(p: Partial<Card> = {}): Card {
  return voucherCard({
    id: "card-mega",
    family: "mega_sale",
    family_label: "Chiến dịch lớn (mega sale)",
    change_kind: "mega_sale",
    title: "Mega sale 11/11 — 3 thay đổi, một ngân sách, một lần duyệt",
    inputs: { budget_cap_per_day: 1_500_000 },
    whatif: { sliders: [{ key: "budget_cap_per_day", label: "Trần chi / ngày", unit: "vnd", min: 0, max: 1_000_000_000, step: 10000, default: 1_500_000 }], children_editable: true },
    mega_window: { start: "2026-11-11T00:00:00", end: "2026-11-13T00:00:00", days: 2 },
    children: megaChildren(),
    schedule: [
      { date: "2026-11-11", events: megaChildren().map((c) => ({ child_id: c.child_id, kind: c.change_kind, action: "bat", at: "00:00" })) },
      { date: "2026-11-12", events: megaChildren().map((c) => ({ child_id: c.child_id, kind: c.change_kind, action: "tat", at: "00:00" })) },
    ],
    certain: {
      label: "Chắc chắn",
      kind: "mega_sale",
      orders_in_window_expected: 80,
      total_discount: 2_400_000,
      by_lever: [
        { lever: "khuyen_mai", lines: 50, discount: 1_800_000 },
        { lever: "voucher", lines: 20, discount: 600_000 },
      ],
      skus: [
        { sku: "BEP-S5-CB", worst_unit_net_revenue: 190000, floor: 181979, below_floor: false },
        { sku: "BEP-S5-LX", worst_unit_net_revenue: 120000, floor: 121176, below_floor: true },
      ],
      no_double_counting: "Đơn được tính lại một lần với mọi thay đổi chồng lên nhau.",
      spend: { cap_per_day: 1_500_000, shop_cap_per_day: 1_200_000, mega_chi_per_day: 1_300_000, baseline_chi_per_day: 1_110_211, over_budget: false, over_shop_cap: true },
    },
    bundle: true,
    execution_sheet: {
      ...SHEET_VOUCHER,
      steps: megaChildren().map((c, i) => ({ order: i + 1, field: `${c.label} (${c.change_kind})`, before: null, after: "xem bảng", copy: null, unit: null, page: c.page, starts: c.starts, child_card_id: null })),
      revert_steps: [],
      changes: [],
    },
    ...p,
  });
}

// ── Journey ─────────────────────────────────────────────────────────────────

export const JOURNEY_EXECUTED: JourneyEvent[] = [
  { event: "proposed", at: "2026-11-03T02:00:00", reason_code: null },
  { event: "accepted", at: "2026-11-04T01:00:00", reason_code: null },
  { event: "executed", at: "2026-11-04T03:00:00", reason_code: null },
];
export const JOURNEY_VERIFIED: JourneyEvent[] = [...JOURNEY_EXECUTED, { event: "verified", at: "2026-11-05T01:00:00", reason_code: null, payload: { observed: { discount_amount: 15000, min_spend: 299000 }, observed_at: "2026-11-05T01:00:00" } }];

// ── Fake API ────────────────────────────────────────────────────────────────

export interface FakeReco extends RecoApi {
  readonly calls: { readonly name: string; readonly args: unknown[] }[];
}

/** Every method resolves with the given payload (or the default); `calls` records name and arguments. */
export function fakeReco(
  data: Partial<{
    list: CardList;
    detail: CardDetail;
    whatif: Card | ((inputs: Readonly<Record<string, unknown>>, version?: number) => Card);
    compare: CompareResult | ((variants: readonly unknown[]) => CompareResult);
    manual: ManualResult;
    byCode: CardByCode;
    execution: ExecutionStates;
    measurements: MeasurementStates;
  }> = {},
  failWith?: Partial<Record<keyof RecoApi, Error>>,
): FakeReco {
  const calls: { name: string; args: unknown[] }[] = [];
  const run = <T,>(name: keyof RecoApi, value: T, ...args: unknown[]): Promise<T> => {
    calls.push({ name, args });
    const err = failWith?.[name];
    return err ? Promise.reject(err) : Promise.resolve(value);
  };
  const detail = data.detail ?? detailOf(voucherCard());
  return {
    calls,
    list: (...a) => run("list", data.list ?? { platform: "shopee", xep_theo: "diem", cards: [summaryOf(voucherCard())], counts: { family: { voucher: 1 }, section: { aov: 1 }, total: 1 } }, ...a),
    detail: (...a) => run("detail", detail, ...a),
    whatif: (id, inputs, version) => run("whatif", typeof data.whatif === "function" ? data.whatif(inputs, version) : (data.whatif ?? detail.card), id, inputs, version),
    approve: (...a) => run("approve", { id: detail.id, status: "approved", approval_id: "ap-1", chosen_version: a[1]?.chosenVersion ?? 1 }, ...a),
    compare: (variants, ...rest) => run("compare", typeof data.compare === "function" ? data.compare(variants) : (data.compare ?? compareResult(variants.length)), variants, ...rest),
    createManual: (...a) => run("createManual", data.manual ?? manualResult(), ...a),
    byCode: (code) => run("byCode", data.byCode ?? ({ code, id: "card-voucher", status: "sent", family: "voucher", change_kind: "min_spend_voucher", title: "Voucher", product_id: "BEP-S5", product_queue: 1, created_at: "2026-11-04T07:10:00", sent_at: null, supersedes_code: null, versions: [], chosen_version: null, chosen_version_code: null, inputs: { default: {} }, change: {}, status_history: [], verification: { state: null } } as CardByCode), code),
    requestChange: (...a) => run("requestChange", { id: detail.id, status: "changes_requested", approval_id: "ap-2" }, ...a),
    dismiss: (...a) => run("dismiss", { id: detail.id, status: "rejected", approval_id: "ap-3" }, ...a),
    executed: (...a) => run("executed", { id: detail.id, status: "executed", execution_id: "ex-1", events: 1 }, ...a),
    generate: (...a) => run("generate", { generated: 3, persisted: 3, by_family: {}, card_ids: [] }, ...a),
    publish: (...a) => run("publish", { sent: ["card-voucher"] }, ...a),
    withdraw: (...a) => run("withdraw", { id: detail.id, status: "withdrawn" }, ...a),
    withdrawMany: (...a) => run("withdrawMany", { withdrawn: [...a[0]], refused: [] }, ...a),
    rerunStale: (...a) => run("rerunStale", { replaced: 1 }, ...a),
    learning: (...a) => run("learning", { calibration: null, acceptance: null, sim: null }, ...a),
    learningRun: (...a) => run("learningRun", {}, ...a),
    executionStates: (...a) => run("executionStates", data.execution ?? { platform: "shopee", connector: { version: null, last_check_at: null, connected: false, seller_centre_open: null }, cards: [], counts: {} }, ...a),
    measurements: (...a) => run("measurements", data.measurements ?? { platform: "shopee", cards: [] }, ...a),
  };
}

// ── Compare and manual (P91 D-3) ────────────────────────────────────────────

const metricsOf = (dp50: number, over: Partial<NonNullable<CompareResult["variants"][number]["metrics"]>> = {}) => ({
  dprofit_p10: dp50 - 120000,
  dprofit_p50: dp50,
  dprofit_p90: dp50 + 160000,
  dprofit_certain: -30000,
  dgmv_p50: 900000 + dp50,
  dorders_p50: 6,
  aov_p50: 4000,
  margin_points_p50: -0.4,
  cost_month: 80000,
  floor_breaches: 0,
  floor_ok: true,
  spend_after_per_day: 1_040_000,
  spend_cap: 1_200_000,
  spend_over_cap: false,
  ...over,
});

/** `n` priced variants; the third one (when asked for) breaks a floor. */
export function compareResult(n = 3): CompareResult {
  const rows = Array.from({ length: n }, (_, i) => {
    const breach = i === 2;
    const floor = breach ? breachedVoucherCard().floor : voucherCard().floor;
    const card = voucherCard({ id: undefined, title: `Combo thử ${i + 1}`, floor });
    return {
      index: i,
      label: `Phương án ${i + 1}`,
      change_kind: "combo_multi",
      ok: true,
      refusal: null,
      title: `Combo thử ${i + 1}`,
      metrics: metricsOf(60000 + i * 20000, breach ? { floor_breaches: 1, floor_ok: false } : {}),
      card,
    };
  });
  return {
    today: { as_of: "2026-11-02", gmv_30d: 19_800_000, orders_30d: 120, aov: 165000, margin_pct: 15.3, spend_per_day: 1_040_000, spend_cap: 1_200_000 },
    variants: rows,
    vs_today: rows.map((r) => ({ index: r.index, delta: { ...r.metrics! } as unknown as Record<string, number | null> })),
    between: [],
    best_profit_p50: 1,
    saved: false,
  };
}

export function manualResult(over: Partial<ManualResult> = {}): ManualResult {
  return {
    id: "card-manual",
    status: "sent",
    origin: "manual",
    position: 50,
    primary: false,
    versions: [
      { index: 1, chosen: true, label: "Phương án 2", metrics: null },
      { index: 0, chosen: false, label: "Phương án 1", metrics: null },
    ],
    card: voucherCard({ id: "card-manual", code: "JC-2611-0015", origin: "manual" }),
    ...over,
  };
}
