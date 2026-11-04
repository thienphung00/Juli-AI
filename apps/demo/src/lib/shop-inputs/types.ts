/** Payloads of `/v1/demo/shop-inputs` and `/v1/ops/shops/{id}/inputs` (P90 step 4). */

export type InputUnit = "vnd" | "pct" | "count" | "date" | "group" | "status";

export interface Affected {
  readonly total: number;
  readonly proposals: number;
  readonly action_cards: number;
  readonly item_ids: readonly string[];
  readonly shop_wide: boolean;
}

export interface FallbackSku {
  readonly item_id: string;
  readonly variation_id: string;
  readonly sku: string;
  readonly name: string;
  readonly list_price: number | null;
  readonly assumed_cost: number | null;
}

/** One shipment of samples on the Mẫu KOL sheet (`kol_samples.Shipment.json`). */
export interface SampleShipment {
  readonly handle: string;
  readonly qty: number;
  /** ISO date. */
  readonly sent_on: string;
  readonly ship_fee: number;
}

/** A KOL × product with samples on record (`overview.samples.items`). */
export interface SamplePair {
  readonly scope_ref: string;
  readonly kol_key: string;
  readonly handle: string;
  readonly item_id: string;
  readonly sku: string;
  readonly shipments: readonly SampleShipment[];
  readonly sample_cost: number | null;
  readonly cost_label: string;
}

export interface InputsOverview {
  readonly samples: { readonly pairs: number; readonly shipments: number; readonly items: readonly SamplePair[] };
  readonly catalogue: { readonly sku_rows: number; readonly items: number; readonly with_cost: number };
  readonly cost_fallback: {
    readonly count: number;
    readonly assumed_share: string;
    readonly margin_pct: number;
    readonly source: string;
    readonly skus: readonly FallbackSku[];
  };
  readonly months: readonly { readonly month: string; readonly values: Readonly<Record<string, number>> }[];
  readonly reasons: readonly string[];
}

export type RejectionKind =
  | "unknown_sku"
  | "cost_ge_price"
  | "cost_missing"
  | "out_of_range"
  | "bad_date"
  | "duplicate_sku"
  | "invalid_value"
  | "bad_month"
  | "kol_missing";

export interface Rejection {
  readonly sheet: string;
  readonly row: number;
  readonly sku: string;
  readonly column: string;
  readonly value: string;
  readonly reason: string;
  readonly kind: RejectionKind;
  readonly kind_label: string;
}

export interface FieldDiff {
  readonly scope_ref: string;
  readonly item_id: string;
  readonly variation_id: string;
  readonly sku: string;
  readonly field: string;
  readonly label: string;
  readonly unit: InputUnit;
  readonly rule_key: string;
  readonly old: unknown;
  readonly new: unknown;
  readonly effect: string;
}

/** One KOL × product whose shipments the Mẫu KOL sheet changes (`_sample_diff_json`). */
export interface SampleDiff {
  readonly scope_ref: string;
  readonly kol_key: string;
  readonly handle: string;
  readonly item_id: string;
  readonly sku: string;
  readonly tag: "Mới" | "Đổi" | "Xoá" | string;
  readonly old: readonly SampleShipment[];
  readonly new: readonly SampleShipment[];
  readonly old_cost: number | null;
  readonly new_cost: number | null;
  readonly cost_label: string;
  /** "Chi phí mẫu 172.000đ → 221.000đ (giá vốn …)". */
  readonly effect: string;
}

export interface GoalWarning {
  readonly month: string;
  readonly message: string;
  readonly deviation: number;
}

export interface ImportPreview {
  readonly file_hash: string;
  readonly counts: {
    readonly sku_rows: number;
    readonly sku_rows_valid: number;
    readonly sku_rows_rejected: number;
    readonly sku_rows_unchanged: number;
    readonly sample_rows: number;
    readonly sample_rows_valid: number;
    readonly sample_rows_rejected: number;
    readonly sample_rows_unchanged: number;
    readonly samples_changed: number;
    readonly goal_rows: number;
    readonly goal_rows_rejected: number;
    readonly changes: number;
    readonly skus_changed: number;
    readonly months_changed: number;
  };
  readonly rejections: readonly Rejection[];
  readonly diffs: readonly FieldDiff[];
  readonly goal_diffs: readonly FieldDiff[];
  readonly sample_diffs: readonly SampleDiff[];
  readonly warnings: readonly GoalWarning[];
  readonly affected: Affected;
}

export interface ApplyResult {
  readonly file_hash: string;
  readonly reason: string;
  readonly applied_at: string;
  readonly versions_written: number;
  readonly skus_changed: number;
  readonly samples_changed: number;
  readonly months_changed: number;
  readonly rejected: number;
  readonly affected: Affected;
}

export interface VersionSku {
  readonly scope_ref: string;
  readonly item_id: string;
  readonly variation_id: string;
  readonly sku: string;
  readonly name: string;
}

export interface ChangeSet {
  readonly id: string;
  readonly number: number;
  readonly valid_from: string;
  readonly set_by: "team" | "seller";
  readonly reason: string | null;
  readonly import_file_hash: string | null;
  readonly changes: Readonly<Record<string, unknown>>;
  readonly state: Readonly<Record<string, unknown>>;
  readonly current: boolean;
}

export interface SkuVersions {
  readonly scope_ref: string;
  readonly versions: readonly ChangeSet[];
  readonly restore_affects: Affected;
}

export interface RestoreResult {
  readonly scope_ref: string;
  readonly restored_from: number;
  readonly new_version: string | null;
  readonly versions_written: number;
  readonly affected: Affected;
}

export interface TemplateFile {
  readonly blob: Blob;
  readonly filename: string;
  readonly skuRows: number;
}

export interface ShopInputsApi {
  overview(): Promise<InputsOverview>;
  template(): Promise<TemplateFile>;
  preview(file: Blob): Promise<ImportPreview>;
  apply(file: Blob, reason: string, fileHash: string): Promise<ApplyResult>;
  versionsIndex(): Promise<readonly VersionSku[]>;
  versions(scopeRef: string): Promise<SkuVersions>;
  restore(scopeRef: string, version: number): Promise<RestoreResult>;
}
