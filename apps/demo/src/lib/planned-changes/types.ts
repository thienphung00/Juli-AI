/** Payloads of `/v1/demo/shop-inputs/planned-changes` and `/v1/ops/shops/{id}/planned-changes` (P91 D-13). */

export type RowAction = "create" | "advance" | "unchanged" | "rejected";

export interface PlannedOverview {
  readonly sheet: string;
  readonly columns: readonly { readonly key: string; readonly label: string }[];
  readonly kinds: readonly { readonly key: string; readonly label: string }[];
  readonly reasons: readonly string[];
  readonly min_window_days: number;
  readonly max_title_chars: number;
}

export interface PlannedProblem {
  readonly row: number;
  readonly ref: string;
  readonly kind: string;
  readonly label: string;
  readonly column: string;
  readonly detail: string;
}

export interface PlannedCardBrief {
  readonly title: string;
  readonly change_kind: string;
  /** False: "không ước tính" (no prior for this change). */
  readonly estimated: boolean;
  readonly dprofit_p10: number | null;
  readonly dprofit_p50: number | null;
  readonly dprofit_p90: number | null;
  readonly note: string | null;
}

export interface PlannedRow {
  readonly row: number;
  readonly ref: string;
  readonly item_id: string;
  readonly change_kind: string | null;
  readonly change_label: string;
  readonly before: string;
  readonly after: string;
  readonly reason: string;
  readonly cost: number | null;
  readonly date: string | null;
  readonly window_days: number | null;
  readonly depends_on: readonly string[];
  readonly decision: "approve" | "reject" | "change" | null;
  readonly decision_label: string;
  readonly status: "pending" | "in_progress" | "done";
  readonly status_label: string;
  readonly action: RowAction;
  readonly problems: readonly PlannedProblem[];
  readonly warnings: readonly PlannedProblem[];
  readonly card: PlannedCardBrief | null;
}

export interface PlannedPreview {
  readonly file_hash: string;
  readonly missing_columns: readonly string[];
  readonly counts: {
    readonly rows: number;
    readonly create: number;
    readonly advance: number;
    readonly unchanged: number;
    readonly rejected: number;
    readonly warnings: number;
  };
  readonly rows: readonly PlannedRow[];
  readonly order: readonly string[];
}

export interface PlannedApplied {
  readonly number: number;
  readonly file_hash: string;
  readonly reason: string;
  readonly applied_at: string;
  readonly created: number;
  readonly advanced: number;
  readonly executed: number;
  readonly unchanged: number;
  readonly rejected: number;
  readonly rows: readonly { readonly ref: string; readonly code: string | null; readonly action: string; readonly executed_on: string | null }[];
}

export interface PlannedImport {
  readonly number: number;
  readonly applied_at: string;
  readonly set_by: "seller" | "staff";
  readonly reason: string;
  readonly file_hash: string;
  readonly counts: Readonly<Record<string, number>>;
  readonly rows?: readonly { readonly ref: string; readonly code: string | null; readonly action: string; readonly executed_on: string | null }[];
}

export interface TemplateFile {
  readonly blob: Blob;
  readonly filename: string;
}

export interface PlannedChangesApi {
  overview(): Promise<PlannedOverview>;
  template(): Promise<TemplateFile>;
  preview(file: Blob): Promise<PlannedPreview>;
  apply(file: Blob, reason: string, fileHash: string): Promise<PlannedApplied>;
  versions(): Promise<readonly PlannedImport[]>;
  version(number: number): Promise<PlannedImport>;
}
