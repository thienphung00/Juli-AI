import { ShopeeApiError } from "../shopee-analytics/client";
import type { OptionResult } from "./option-result";

/**
 * P98 client of the three builder routes (all POST, active shop, nothing is written):
 * `/builder/combo/options`, `/builder/kol/setup`, `/builder/ads/setup`. Shapes mirror
 * `backend/.../api/routes/demo_shopee_builder_p98.py` and `services/shopee_builder/specs_p98.py`.
 * `result` (an `OptionResult`) is added to each row / setup by the integration slice; optional here.
 */

type N = number | null;

// ── combo ────────────────────────────────────────────────────────────────

export interface ComboProductPick {
  readonly item_id: string;
  readonly variation_ids: readonly string[];
}
export interface ComboBundle {
  readonly items: readonly { readonly item_id: string; readonly quantity: number }[];
}
export interface ComboRules {
  readonly same_variation: boolean;
  readonly sold_only: boolean;
  readonly max_options: number;
  readonly shop_code?: string;
  readonly unit?: string;
}
export interface ComboPriceRule {
  readonly kind: "ladder" | "target_margin" | "per_box";
  readonly ladder?: readonly { readonly units: number; readonly discount_pct: number }[];
  readonly target_margin_pct?: number;
  readonly box_price?: number;
  readonly round_to?: number;
  readonly ending_9?: boolean;
}
export interface ComboRequest {
  readonly products: readonly ComboProductPick[];
  readonly pack_sizes: readonly number[];
  readonly bundles: readonly ComboBundle[];
  readonly rules: ComboRules;
  readonly price_rule: ComboPriceRule;
  readonly floor_pct?: number;
  readonly overrides?: Readonly<Record<string, number>>;
  readonly as_of?: string;
}
export interface ComboMember {
  readonly item_id: string;
  readonly product_name: string;
  readonly variation_id: string | null;
  readonly variation_name: string | null;
  readonly quantity: number;
  readonly unit_price: N;
}
export interface ComboRow {
  readonly key: string;
  readonly form: string;
  readonly name: string;
  readonly option_name: string;
  readonly sku: string | null;
  readonly units: number;
  readonly members: readonly ComboMember[];
  readonly suggested_stock: N;
  readonly stock_note: string | null;
  readonly price: N;
  readonly price_per_box: N;
  readonly separate_total: N;
  readonly saving: N;
  readonly saving_pct: N;
  readonly margin_pct: N;
  readonly final_margin_pct: N;
  readonly final_rates?: unknown;
  readonly profit_per_order: N;
  readonly margin_label: string | null;
  readonly below_floor: boolean;
  readonly floor_basis?: string | null;
  readonly overridden: boolean;
  readonly basis?: string | null;
  readonly notes: readonly string[];
  readonly inputs?: unknown;
  readonly result?: OptionResult | null;
}
export interface ComboResponse {
  readonly as_of: string;
  readonly count: { readonly total: number; readonly kept: number; readonly over_cap: number; readonly by_form: Readonly<Record<string, number>> };
  readonly warnings: readonly string[];
  readonly margin_basis?: Readonly<Record<string, string>> | string | null;
  readonly floor_pct: N;
  readonly variations?: unknown;
  readonly rows: readonly ComboRow[];
}

// ── KOL ──────────────────────────────────────────────────────────────────

export interface KolSetupRequestItem {
  readonly kol_key: string;
  readonly item_ids: readonly string[];
  readonly commission_pct: number;
  readonly sample?: { readonly item_id: string; readonly qty: number; readonly ship_fee: number };
}
export interface KolRequest {
  readonly kols: readonly KolSetupRequestItem[];
  readonly as_of?: string;
}
export interface KolInfo {
  readonly kol_key: string;
  readonly handle: string | null;
  readonly channel: string | null;
  readonly orders_seen?: number;
  readonly partner_orders?: N;
  readonly clicks_per_30d?: N;
  readonly conversion?: N;
  readonly typical_sample_qty?: N;
  readonly last_ship_fee?: N;
}
export interface KolSample {
  readonly item_id: string;
  readonly qty: number;
  readonly ship_fee: number;
  readonly unit_cost: N;
  readonly unit_cost_basis: string | null;
  readonly cost: N;
  readonly cost_note: string | null;
}
export interface KolSetupRow {
  readonly kol: KolInfo;
  readonly commission_pct: number;
  readonly products: readonly { readonly item_id: string; readonly name: string; readonly current_commission_rate: N; readonly measured_note?: string | null }[];
  readonly sample: KolSample | null;
  readonly inputs?: unknown;
  readonly result?: OptionResult | null;
}
export interface KolResponse {
  readonly as_of: string;
  readonly window?: unknown;
  readonly setups: readonly KolSetupRow[];
  readonly labels: Readonly<Record<string, string>>;
}

// ── ads ──────────────────────────────────────────────────────────────────

export interface AdsSetupRequestItem {
  readonly campaign: "group" | "single";
  readonly item_ids: readonly string[];
  readonly daily_budget: number;
  readonly roas: { readonly mode: "system" | "custom"; readonly target?: number };
  readonly start_date: string;
  readonly end_date?: string;
  readonly name?: string;
}
export interface AdsRequest {
  readonly setups: readonly AdsSetupRequestItem[];
  readonly as_of?: string;
}
export interface AdsSetupRow {
  readonly campaign: "group" | "single";
  readonly campaign_label: string;
  readonly name: string | null;
  readonly daily_budget: number;
  readonly days: N;
  readonly total_budget: N;
  readonly products: readonly { readonly item_id: string; readonly name: string; readonly measured: boolean; readonly note: string | null; readonly roas_broad?: N; readonly spend?: N }[];
  readonly inputs?: unknown;
  readonly result?: OptionResult | null;
}
export interface AdsResponse {
  readonly as_of: string;
  readonly budget_minimum: number;
  readonly setups: readonly AdsSetupRow[];
}

export interface BuilderP98Api {
  combo(req: ComboRequest): Promise<ComboResponse>;
  kol(req: KolRequest): Promise<KolResponse>;
  ads(req: AdsRequest): Promise<AdsResponse>;
}

const BY_STATUS: Readonly<Record<number, string>> = {
  401: "Phiên đăng nhập đã hết hạn. Đăng nhập lại rồi thử lại.",
  404: "Không tìm thấy sản phẩm, phân loại hoặc KOL này trong shop. Chọn lại rồi thử lại.",
  409: "Dữ liệu shop đang được cập nhật. Thử lại sau ít phút.",
  422: "Thông số chưa hợp lệ. Kiểm tra lại các ô vừa nhập.",
};

export function p98ErrorText(status: number): string {
  return BY_STATUS[status] ?? `Không tính được (lỗi ${status}). Thử lại hoặc đổi thông số.`;
}

function errorOf(status: number, payload: unknown): ShopeeApiError {
  let code = "";
  let message = p98ErrorText(status);
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "object" && detail !== null && !Array.isArray(detail)) {
      const d = detail as { code?: unknown; message?: unknown };
      if (typeof d.code === "string") code = d.code;
      if (typeof d.message === "string" && d.message) message = d.message;
      return new ShopeeApiError(status, code, message, detail as Readonly<Record<string, unknown>>);
    }
    if (typeof detail === "string" && status !== 401 && status !== 422) message = detail;
  }
  return new ShopeeApiError(status, code, message);
}

export interface BuilderP98Options {
  readonly base: string;
  readonly token: string;
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

export function createBuilderP98Api(options: BuilderP98Options): BuilderP98Api {
  const { base, token, shopId, fetchImpl } = options;
  async function post<T>(path: string, body: unknown): Promise<T> {
    const response = await (fetchImpl ?? fetch)(`${base}${path}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(shopId ? { "X-Shop-Id": shopId } : {}),
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) throw errorOf(response.status, payload);
    return payload as T;
  }
  return {
    combo: (req) => post<ComboResponse>("/builder/combo/options", req),
    kol: (req) => post<KolResponse>("/builder/kol/setup", req),
    ads: (req) => post<AdsResponse>("/builder/ads/setup", req),
  };
}
