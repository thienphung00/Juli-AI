import type { N } from "../shopee-decisions/types";

/**
 * KOL × sản phẩm × kênh (P91 D-9 / D-11). The KOL backend is built in parallel: every field here is
 * an ASSUMPTION taken from the artboards (`PhanTichKOL`, `SanPhamLienKet`, `CardKOL`, `CaiDatMauKOL`) and
 * `fasttrack/contracts/p91-plan.md`; the orchestrator reconciles them when the routes land.
 *   GET {shopee-analytics base}/kol            -> {@link KolReport}
 *   card `affiliate_sample` / `affiliate_invite` -> `certain.kol` on each version ({@link KolCert})
 *   {shop-inputs base}/kol-samples/{template,preview,apply} -> {@link KolSamplesApi}
 */

export type KolCardKind = "affiliate_sample" | "affiliate_invite";

export interface KolRow {
  /** Hashed affiliate key (the raw id is never stored). */
  readonly kol_key: string;
  /** Public handle. */
  readonly handle: string;
  /** "Shopee Video" · "Facebook" · "TikTok" … */
  readonly channel: string;
  readonly product_id: string;
  readonly product_name: string;
  readonly orders: number;
  readonly units: number;
  readonly gmv: number;
  readonly clicks: number;
  /** orders ÷ clicks, a fraction. */
  readonly conversion: N;
  readonly commission: number;
  readonly net_profit: number;
  readonly sample_cost: number;
  readonly profit_after_samples: number;
  /** (net − sample) ÷ (commission + sample), a fraction; null when there is nothing to divide by. */
  readonly roi_with_samples: N;
  /** The `ROI` of Shopee's KOL export, as it came ("9,8"); never recomputed. */
  readonly roi_shopee: string | number | null;
  readonly payback_orders: number | null;
  /** Fewer than 10 orders for the KOL × product pair. */
  readonly few_data: boolean;
  /** The open Gửi mẫu / Mời KOL card for this pair, when there is one. */
  readonly card: { readonly id: string; readonly code: string; readonly kind: KolCardKind } | null;
}

export interface KolReport {
  readonly window: { readonly from: string; readonly to: string; readonly days: number };
  readonly rows: readonly KolRow[];
  readonly channels: readonly string[];
  /** The commission rate (fraction) that applies to each product now. */
  readonly product_rates: Readonly<Record<string, number>>;
}

export interface KolApi {
  report(): Promise<KolReport>;
}

/** `certain.kol` of a Gửi mẫu / Mời KOL card version. */
export interface KolCert {
  readonly kol: { readonly key: string; readonly handle: string; readonly channel: string };
  readonly invite: boolean;
  readonly product_id: string;
  readonly product_name: string;
  /** Mẫu gửi; null for an invitation. */
  readonly qty: number | null;
  readonly commission_pct: number;
  readonly current_commission_pct: N;
  readonly sample: { readonly unit_cost: N; readonly ship: N; readonly cost: number };
  readonly expected: {
    readonly orders: { readonly p10: N; readonly p90: N };
    readonly net: { readonly p10: N; readonly p90: N };
    readonly profit_after_samples: { readonly p10: N; readonly p90: N };
    readonly roi: { readonly p10: N; readonly p90: N } | null;
    readonly payback_orders: number | null;
    readonly net_per_order: N;
    readonly commission_per_order: N;
  };
  readonly few_data: boolean;
  /** "KOL 14 đơn / 310 lượt nhấp, riêng sản phẩm này 9 đơn". */
  readonly basis: string;
  readonly product_options: readonly { readonly product_id: string; readonly name: string; readonly commission_pct: number }[];
}

// ── Mẫu KOL sheet ───────────────────────────────────────────────────────────

export interface KolSampleRow {
  readonly kol: string;
  readonly product: string;
  readonly qty: number;
  readonly sent_on: string | null;
  readonly ship: N;
  readonly note?: string;
}

export interface KolSamplesPreview {
  readonly file_hash: string;
  readonly current_version: number;
  readonly rows_valid: number;
  readonly rows_rejected: number;
  readonly checks: readonly { readonly row: number; readonly kol: string; readonly product: string; readonly ok: boolean; readonly message: string }[];
  readonly diffs: readonly {
    readonly kol: string;
    readonly product_name: string;
    readonly tag: "Đổi" | "Thêm mới" | string;
    readonly cells: readonly { readonly label: string; readonly old: string; readonly new: string }[];
    readonly consequence: string;
  }[];
  readonly cards_recalculated: readonly string[];
}

export interface KolSamplesOverview {
  readonly version: number;
  readonly rows: readonly KolSampleRow[];
  readonly filename: string | null;
  readonly reasons: readonly string[];
}

export interface KolSamplesApplied {
  readonly version: number;
  readonly cards_recalculated: readonly string[];
}

export interface KolSamplesApi {
  overview(): Promise<KolSamplesOverview>;
  template(): Promise<{ readonly blob: Blob; readonly filename: string }>;
  preview(file: Blob): Promise<KolSamplesPreview>;
  apply(file: Blob, reason: string, fileHash: string): Promise<KolSamplesApplied>;
}
