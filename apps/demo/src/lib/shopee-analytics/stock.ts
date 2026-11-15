/**
 * P100 Part S: the stock rows of Sản phẩm (product page, and the list from the e-mail) and the
 * per-variation "Theo dõi" switch
 * (`/v1/demo/shopee/stock`, seller only), plus the e-mail's unsubscribe confirm
 * (`/v1/stock-alert/unsubscribe`, no sign-in: the signed token is the credential).
 */

export const DEMO_STOCK_BASE = "/v1/demo/shopee/stock" as const;
export const UNSUBSCRIBE_PATH = "/v1/stock-alert/unsubscribe" as const;

export interface StockRow {
  readonly key: string;
  readonly item_id: string;
  readonly model_id: string;
  readonly product_name: string;
  readonly variation_name: string | null;
  readonly sku_code: string | null;
  readonly stock: number | null;
  readonly units_per_day: number | null;
  readonly days_left: number | null;
  readonly runs_out_on: string | null;
  readonly out_of_stock: boolean;
  readonly out_since: string | null;
  readonly read_at: string | null;
  readonly tracked: boolean;
  readonly eligible: boolean;
  readonly soon: boolean;
}

export interface StockList {
  readonly enabled: boolean;
  readonly alert_days?: number;
  readonly rows: readonly StockRow[];
}

export interface StockApi {
  list(): Promise<StockList>;
  setTracked(key: string, tracked: boolean): Promise<{ readonly key: string; readonly tracked: boolean }>;
}

export function createStockApi(options: { readonly token: string; readonly shopId: string; readonly fetchImpl?: typeof fetch }): StockApi {
  const { token, shopId, fetchImpl } = options;
  const headers = { Accept: "application/json", Authorization: `Bearer ${token}`, "X-Shop-Id": shopId };
  async function call<T>(method: "GET" | "PUT", path: string, body?: unknown): Promise<T> {
    const response = await (fetchImpl ?? fetch)(`${DEMO_STOCK_BASE}${path}`, {
      method,
      headers: body === undefined ? headers : { ...headers, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = (await response.json()) as { data: T };
    return payload.data;
  }
  return {
    list: () => call<StockList>("GET", ""),
    setTracked: (key, tracked) => call("PUT", `/${encodeURIComponent(key)}/tracking`, { tracked }),
  };
}

export async function confirmUnsubscribe(token: string, fetchImpl?: typeof fetch): Promise<boolean> {
  const response = await (fetchImpl ?? fetch)(UNSUBSCRIBE_PATH, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
    cache: "no-store",
  });
  return response.ok;
}

/** "2026-11-22" → "22/11". */
export function dayMonthOf(iso: string | null): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  return m ? `${m[3]}/${m[2]}` : null;
}

/** "Còn 42 · hết khoảng 22/11"; out of stock "Hết hàng"; no read "—". */
export function stockText(row: StockRow): string {
  if (row.stock === null) return "—";
  if (row.out_of_stock) return "Hết hàng";
  const day = dayMonthOf(row.runs_out_on);
  return day ? `Còn ${row.stock} · hết khoảng ${day}` : `Còn ${row.stock}`;
}

/** "Đỏ · SKU AT-DO" (the variation, then the seller's SKU code when known). */
export function variationText(row: StockRow): string {
  const parts = [row.variation_name ?? (row.model_id ? row.model_id : row.product_name)];
  if (row.sku_code) parts.push(`SKU ${row.sku_code}`);
  return parts.join(" · ");
}

/** The `ton_kho` filter of the e-mail's "Mở Juli" link: "1:11,2:21". */
export function stockFilterOf(params: URLSearchParams): readonly string[] {
  return (params.get("ton_kho") ?? "")
    .split(",")
    .map((k) => k.trim())
    .filter((k) => /^[0-9]{1,64}(:[0-9]{1,64})?$/.test(k));
}
