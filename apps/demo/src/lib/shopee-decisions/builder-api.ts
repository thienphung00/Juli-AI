import { ShopeeApiError } from "../shopee-analytics/client";

/**
 * P92 client of the builder API (`fasttrack/contracts/p92-api.md`): the product picker, variations,
 * the version evaluator / comparer / chooser, keyword table and LLM drafts, and the exclusions rule.
 * Same paths for the seller (`/v1/demo/shopee`) and Juli Ops (`/v1/ops/shops/{id}/shopee`).
 */

export const DEMO_BUILDER_BASE = "/v1/demo/shopee" as const;

export function opsBuilderBase(shopId: string): string {
  return `/v1/ops/shops/${encodeURIComponent(shopId)}/shopee`;
}

/** The P92 builder is on; `NEXT_PUBLIC_P92_BUILDER=0` falls back to the P91 builder (kill switch). */
export function p92BuilderEnabled(): boolean {
  return process.env.NEXT_PUBLIC_P92_BUILDER !== "0";
}

type N = number | null;

// ── B-1 picker, exclusions ───────────────────────────────────────────────

export type ProductSort = "gmv_90d" | "orders_90d" | "orders_30d" | "name";

export interface PickerProduct {
  readonly item_id: string;
  readonly name: string;
  readonly status?: string | null;
  readonly orders_30d: number;
  readonly orders_90d: number;
  readonly gmv_30d: N;
  readonly gmv_90d: N;
  readonly gmv_basis?: string | null;
  readonly price: N;
  readonly stock: N;
  readonly variation_count: number;
  readonly has_cost: boolean;
  readonly variations_with_cost?: number;
  readonly missing_cost_chip: string | null;
  readonly excluded: boolean;
  readonly exclude_reason: string | null;
}

export interface PickerResult {
  readonly platform?: string;
  readonly window: { readonly from: string; readonly to: string; readonly days: number };
  readonly sort: ProductSort;
  readonly count: number;
  readonly offset: number;
  readonly limit: number;
  readonly excluded_hidden: number;
  readonly missing_cost_count: number;
  readonly products: readonly PickerProduct[];
}

export interface PickerQuery {
  readonly q?: string;
  readonly sort?: ProductSort;
  readonly limit?: number;
  readonly offset?: number;
  readonly includeExcluded?: boolean;
}

export interface ExclusionReason {
  readonly key: string;
  readonly label: string;
}

export interface ExclusionRow {
  readonly item_id: string;
  readonly name: string;
  readonly reason: string;
  readonly reason_label: string;
  readonly set_by?: string | null;
  readonly set_at?: string | null;
  readonly note?: string | null;
  /** Optional figures the server may add. */
  readonly gmv_30d?: N;
  readonly gmv_90d?: N;
}

export interface ExclusionList {
  readonly excluded: readonly ExclusionRow[];
  readonly count: number;
  readonly reasons: readonly ExclusionReason[];
}

// ── B-2 variations ───────────────────────────────────────────────────────

export interface VariationRow {
  readonly variation_id: string;
  readonly name: string;
  readonly sku?: string | null;
  readonly list_price: N;
  readonly selling_price: N;
  readonly pack_count: N;
  readonly pack_source?: "set" | "name" | "single" | string | null;
  readonly pack_source_label?: string | null;
  readonly price_per_unit: N;
  readonly margin_pct: N;
  readonly profit_per_unit: N;
  readonly margin_label: string | null;
  readonly margin_reason: string | null;
  readonly has_cost: boolean;
  readonly stock: N;
  /** Orders of the variation in the last 30 days, when the server sends it (P96). */
  readonly orders_30d?: N;
}

export interface VariationList {
  readonly item_id: string;
  readonly name: string;
  readonly excluded: boolean;
  readonly exclude_reason: string | null;
  readonly columns: readonly string[];
  readonly margin_basis: string;
  readonly vat?: { readonly label?: string | null } | null;
  readonly missing_cost: readonly string[];
  readonly variations: readonly VariationRow[];
}

export interface CoPurchase {
  readonly anchor: { readonly item_id: string; readonly name: string };
  readonly orders_with_anchor: number;
  readonly orders_total: number;
  readonly suggestions: readonly {
    readonly item_id: string;
    readonly name: string;
    readonly together: number;
    readonly orders_with_partner: number;
    readonly share_of_anchor_orders: N;
    readonly share_of_partner_orders: N;
  }[];
}

export interface AdsCampaigns {
  readonly daily_cap: N;
  readonly cap_rule?: string | null;
  readonly campaigns: readonly {
    readonly campaign_key: string;
    readonly name: string;
    readonly running?: boolean;
    readonly daily_budget: N;
    readonly roas_target: N;
    readonly spend_per_day: N;
    readonly roas_direct: N;
    readonly break_even_roas: N;
    readonly products: readonly {
      readonly item_id: string;
      readonly name: string;
      readonly spend: N;
      readonly roas_direct: N;
      readonly break_even_roas: N;
      readonly below_break_even: boolean;
      readonly excluded?: boolean;
    }[];
  }[];
}

// ── B-4 versions ─────────────────────────────────────────────────────────

/** One version in a request: `kind` plus the kind's own fields (see the table in p92-api.md §3). */
export interface BuilderVersion {
  readonly kind: string;
  readonly label?: string;
  readonly [field: string]: unknown;
}

export interface Band {
  readonly low: N;
  readonly p50: N;
  readonly high: N;
}

export interface DriverMetric {
  readonly key: string;
  readonly label: string;
  readonly unit: "vnd" | "pct" | "count" | "ratio" | string;
  readonly before: N;
  readonly after_p50: N;
}

export interface BuilderWarning {
  readonly type: string;
  readonly message?: string;
  readonly sku?: string;
  readonly kind?: string;
  readonly floor?: N;
  readonly min_unit_price?: N;
  readonly [extra: string]: unknown;
}

export interface BuilderOutcome {
  readonly index: number;
  readonly kind: string;
  readonly label: string;
  readonly ok: boolean;
  readonly refusal?: { readonly code?: string; readonly message?: string } | string | null;
  readonly title?: string;
  readonly card_kind?: string;
  readonly change_kind?: string;
  readonly driver?: {
    readonly metrics: readonly DriverMetric[];
    readonly target_metric?: string | null;
    readonly relative_lift?: Readonly<Record<string, N>> | null;
  };
  readonly delta?: {
    readonly gmv: Band | null;
    readonly orders: Band | null;
    readonly profit: Band | null;
    readonly certain_profit?: N;
    readonly orders_note?: string | null;
    /** The figures above cover `days` days (the change's own, up to 30). */
    readonly per?: string;
    readonly days?: number;
    readonly per_day?: { readonly gmv: Band | null; readonly orders: Band | null; readonly profit: Band | null; readonly cost: N } | null;
    readonly period?: { readonly days: number; readonly gmv: Band | null; readonly orders: Band | null; readonly profit: Band | null; readonly cost: N } | null;
    readonly per_order?: { readonly basis: "order" | "voucher_use"; readonly orders: number; readonly cost: N; readonly profit: Band | null } | null;
  };
  readonly voucher?: import("./types").VoucherDetail | null;
  /** Inputs that differ from P1 without changing the result, named (compare only). */
  readonly same_as_first_notes?: readonly string[];
  readonly margin_before_pct?: N;
  readonly margin_after_pct?: N;
  readonly profit_status?: "ok" | "chua_tinh" | string;
  readonly cost_known?: boolean;
  readonly cost?: {
    readonly amount: N;
    readonly period_days?: N;
    readonly per_unit?: N;
    readonly label?: string | null;
    readonly low?: N;
    readonly high?: N;
    readonly expected_units?: N;
    readonly sample?: { readonly qty: number; readonly unit_cost: N; readonly ship_fee: N; readonly total: N } | null;
  } | null;
  /** P96d: the orders this version's "hôm nay" figures stand on (shop, or its products). */
  readonly base?: { readonly scope: "shop" | "product" | string; readonly items: readonly string[]; readonly aov: N; readonly margin_pct: N } | null;
  readonly break_even?: {
    readonly applies: boolean;
    /** P96: "aov" for a basket-size lever (voucher) — it pays back through the AOV of the orders that use it. */
    readonly basis?: "aov" | string;
    readonly aov_now?: N;
    readonly aov_needed?: N;
    readonly extra_orders: N;
    readonly period_days?: N;
    readonly ctor_now?: N;
    readonly ctor_needed?: N;
    readonly reason?: string | null;
    readonly ctor_reason?: string | null;
    /** Vietnamese texts of the two reasons, when the server sends them (P96). */
    readonly reason_text?: string | null;
    readonly ctor_reason_text?: string | null;
  } | null;
  readonly basis?: { readonly key: "product_history" | "shop" | "prior" | "insufficient" | string; readonly label: string; readonly detail?: string | null } | null;
  readonly warnings?: readonly BuilderWarning[];
  readonly breach?: boolean;
  readonly details?: Readonly<Record<string, unknown>>;
}

export interface TableRowBand {
  readonly key: string;
  readonly label?: string;
  readonly unit: "vnd" | "band" | "pct" | "driver" | string;
  readonly values: readonly unknown[];
}

export interface BuilderEvaluation {
  readonly saved: false;
  readonly best_profit_p50: number | null;
  readonly today: {
    readonly as_of?: string;
    readonly gmv_30d: N;
    readonly orders_30d: N;
    readonly aov: N;
    readonly margin_pct: N;
    readonly spend_per_day?: N;
    readonly spend_cap?: N;
  };
  readonly table: { readonly rows: readonly TableRowBand[] };
  readonly versions: readonly BuilderOutcome[];
}

export interface BuilderBreach {
  readonly type: string;
  readonly sku?: string;
  readonly floor?: N;
  readonly min_unit_price?: N;
  readonly [extra: string]: unknown;
}

export interface ChooseResult {
  readonly id: string;
  readonly code?: string | null;
  readonly status: string;
  readonly origin?: string;
  readonly position?: number;
  readonly primary?: boolean;
  readonly product_queue?: number | null;
  readonly versions?: readonly { readonly index?: number; readonly chosen?: boolean; readonly label?: string; readonly status?: string }[];
  readonly outcome?: BuilderOutcome;
}

export interface KeywordRow {
  readonly keyword: string;
  readonly sources: readonly string[];
  readonly volume: N;
  readonly difficulty: N;
  readonly cpc_min?: N;
  readonly cpc_max?: N;
  readonly volume_status?: string | null;
  readonly in_title: boolean;
  readonly role?: string | null;
  readonly competitor_titles?: number;
  readonly ads?: { readonly spend: N; readonly clicks: N; readonly orders: N; readonly gmv: N; readonly roas: N } | null;
}

export interface KeywordTable {
  readonly item_id: string;
  readonly title: string;
  readonly title_chars: number;
  readonly max_title_chars: number;
  readonly sources: readonly { readonly key: string; readonly label: string; readonly present: boolean; readonly count: number; readonly reason: string | null }[];
  readonly keywords: readonly KeywordRow[];
}

export interface TitleDraft {
  readonly title: string;
  readonly chars: number;
  readonly keywords?: { readonly covered: readonly string[]; readonly missing: readonly string[] };
  readonly note?: string | null;
}

export interface TitleDrafts {
  readonly item_id: string;
  readonly current_title?: string;
  readonly max_chars: number;
  readonly drafts: readonly TitleDraft[];
  readonly dropped?: readonly { readonly text: string; readonly reason: string }[];
  readonly warnings?: readonly unknown[];
}

export interface CoverOverlay {
  readonly layout: "banner_top" | "banner_bottom" | "corner_tag" | string;
  readonly price_vnd?: number | null;
  readonly original_price_vnd?: number | null;
  readonly discount_pct?: number | null;
  readonly voucher_text?: string | null;
  readonly pack_text?: string | null;
  readonly badge_text?: string | null;
  readonly hook_text?: string | null;
}

export interface CoverDrafts {
  readonly concepts: readonly { readonly overlay: CoverOverlay; readonly variation_id?: string | null; readonly hook_text?: string | null; readonly rationale?: string | null }[];
  readonly dropped?: readonly unknown[];
  readonly layouts?: readonly string[];
  readonly note?: string | null;
}

export interface DescriptionDrafts {
  readonly drafts: readonly { readonly first_line: string; readonly chars: number; readonly note?: string | null }[];
  readonly dropped?: readonly unknown[];
  readonly max_chars: number;
}

export interface BuilderApi {
  products(q?: PickerQuery): Promise<PickerResult>;
  variations(itemId: string): Promise<VariationList>;
  coPurchase(itemId: string): Promise<CoPurchase>;
  adsCampaigns(): Promise<AdsCampaigns>;
  keywords(itemId: string): Promise<KeywordTable>;
  evaluate(versions: readonly BuilderVersion[]): Promise<BuilderEvaluation>;
  compare(versions: readonly BuilderVersion[]): Promise<BuilderEvaluation>;
  choose(body: { readonly versions: readonly BuilderVersion[]; readonly chosen: number; readonly primary?: boolean; readonly acknowledgeBreaches?: boolean }): Promise<ChooseResult>;
  draftTitle(body: { readonly itemId: string; readonly keywords: readonly string[]; readonly count?: number }): Promise<TitleDrafts>;
  draftCover(body: { readonly itemId: string; readonly count?: number }): Promise<CoverDrafts>;
  draftDescription(body: { readonly itemId: string; readonly count?: number }): Promise<DescriptionDrafts>;
  exclusions(): Promise<ExclusionList>;
  exclude(itemId: string, reason: string, note?: string | null): Promise<ExclusionRow>;
  undoExclusion(itemId: string, note?: string | null): Promise<void>;
}

/** The Vietnamese name of a version field, for a server validation error (`loc[-1]`). */
export const FIELD_LABELS: Readonly<Record<string, string>> = {
  value: "Giá trị",
  min_spend: "Đơn tối thiểu",
  max_value: "Giảm tối đa",
  usage_limit: "Số lượt dùng tối đa",
  per_buyer_limit: "Giới hạn mỗi người",
  start: "Bắt đầu",
  end: "Kết thúc",
  qty: "Số lượng",
  pct: "% giảm",
  price: "Giá",
  limit_per_order: "Giới hạn mỗi đơn",
  unit_cost: "Chi phí mỗi quà",
  packaging: "Đóng gói mỗi quà",
  amount: "Đơn tối thiểu",
  discount_pct: "% giảm",
  final_price: "Giá mới",
  change_pct: "Thay đổi (%)",
  units: "Số lượng (suất)",
  slot_hours: "Số giờ của khung",
  pack_count: "Số lượng trong gói",
  stock: "Tồn",
  bid: "Giá thầu",
  daily_budget: "Ngân sách mỗi ngày",
  roas_target: "ROAS mục tiêu",
  title: "Tiêu đề",
  first_line: "Dòng đầu mô tả",
  commission_pct: "Hoa hồng",
  sample_qty: "Số mẫu gửi",
  sample_ship_fee: "Phí ship mỗi mẫu",
  name: "Tên phân loại",
  sku: "SKU",
  label: "Tên",
};

/** A pydantic `detail` list -> "Thông số chưa hợp lệ: Giá trị, Kết thúc." (never a bare HTTP code). */
function validationMessage(detail: readonly unknown[]): string {
  const names: string[] = [];
  for (const d of detail) {
    const loc = typeof d === "object" && d !== null && Array.isArray((d as { loc?: unknown }).loc) ? (d as { loc: unknown[] }).loc : [];
    const last = [...loc].reverse().find((x) => typeof x === "string" && x !== "body" && x !== "versions");
    const name = typeof last === "string" ? FIELD_LABELS[last] : undefined;
    if (name && !names.includes(name)) names.push(name);
  }
  return names.length > 0 ? `Thông số chưa hợp lệ: ${names.join(", ")}.` : "Thông số chưa hợp lệ. Kiểm tra lại các ô vừa nhập.";
}

export const fallbackErrorText = (status: number): string => `Không tính được phương án này (lỗi ${status}). Thử lại hoặc đổi thông số.`;

function errorOf(status: number, payload: unknown): ShopeeApiError {
  let code = "";
  let message = fallbackErrorText(status);
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) return new ShopeeApiError(status, "invalid_input", validationMessage(detail));
    else if (typeof detail === "object" && detail !== null) {
      const d = detail as { code?: unknown; message?: unknown };
      if (typeof d.code === "string") code = d.code;
      if (typeof d.message === "string") message = d.message;
      return new ShopeeApiError(status, code, message, detail as Readonly<Record<string, unknown>>);
    }
  }
  return new ShopeeApiError(status, code, message);
}

export interface BuilderClientOptions {
  /** `DEMO_BUILDER_BASE` or `opsBuilderBase(shopId)`. */
  readonly base: string;
  readonly token: string;
  /** Seller scope only: the acting shop (`X-Shop-Id`). */
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

export function createBuilderApi(options: BuilderClientOptions): BuilderApi {
  const { base, token, shopId, fetchImpl } = options;
  async function call<T>(method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: unknown, params?: URLSearchParams): Promise<T> {
    const qs = params?.toString();
    const response = await (fetchImpl ?? fetch)(`${base}${path}${qs ? `?${qs}` : ""}`, {
      method,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(shopId ? { "X-Shop-Id": shopId } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      cache: "no-store",
    });
    let payload: unknown = null;
    if (response.status !== 204) {
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
    }
    if (!response.ok) throw errorOf(response.status, payload);
    return payload as T;
  }
  const item = (id: string) => encodeURIComponent(id);
  return {
    products: (q = {}) => {
      const p = new URLSearchParams();
      if (q.q) p.set("q", q.q);
      if (q.sort) p.set("sort", q.sort);
      if (q.limit) p.set("limit", String(q.limit));
      if (q.offset) p.set("offset", String(q.offset));
      if (q.includeExcluded) p.set("include_excluded", "true");
      return call<PickerResult>("GET", "/builder/products", undefined, p);
    },
    variations: (id) => call<VariationList>("GET", `/builder/products/${item(id)}/variations`),
    coPurchase: (id) => call<CoPurchase>("GET", `/builder/products/${item(id)}/co-purchase`),
    adsCampaigns: () => call<AdsCampaigns>("GET", "/builder/ads/campaigns"),
    keywords: (id) => call<KeywordTable>("GET", `/builder/products/${item(id)}/keywords`),
    evaluate: (versions) => call<BuilderEvaluation>("POST", "/builder/evaluate", { versions }),
    compare: (versions) => call<BuilderEvaluation>("POST", "/builder/compare", { versions }),
    choose: (b) =>
      call<ChooseResult>("POST", "/builder/choose", {
        versions: b.versions,
        chosen: b.chosen,
        primary: b.primary ?? false,
        acknowledge_breaches: b.acknowledgeBreaches ?? false,
      }),
    draftTitle: (b) => call<TitleDrafts>("POST", "/builder/drafts/title", { item_id: b.itemId, keywords: b.keywords, count: b.count ?? 3 }),
    draftCover: (b) => call<CoverDrafts>("POST", "/builder/drafts/cover", { item_id: b.itemId, count: b.count ?? 3 }),
    draftDescription: (b) => call<DescriptionDrafts>("POST", "/builder/drafts/description", { item_id: b.itemId, count: b.count ?? 3 }),
    exclusions: () => call<ExclusionList>("GET", "/exclusions"),
    exclude: (id, reason, note) => call<ExclusionRow>("PUT", `/exclusions/${item(id)}`, { reason, ...(note ? { note } : {}) }),
    undoExclusion: async (id, note) => {
      await call<unknown>("DELETE", `/exclusions/${item(id)}`, undefined, note ? new URLSearchParams({ note }) : undefined);
    },
  };
}
