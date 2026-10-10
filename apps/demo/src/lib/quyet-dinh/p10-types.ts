/**
 * Wire shapes of the P10 contract (`fasttrack/contracts/p10-quyet-dinh.md`),
 * field for field. P10-A / P10-B implement them in parallel; until they are
 * merged every field here is OPTIONAL on the wire and the UI degrades
 * (`card-model.ts` falls back to the P7-B diagnosis, Đo lường to the
 * completion date). Kept local to the demo app like `types.ts`.
 */

import type { DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";

/** §1 `recommendation.card.status`. */
export type CardStatus = "pending" | "running" | "applied" | "rejected" | "expired";

/** §1 lever executors. */
/** P14-E: `juli_drafts` = "Juli soạn · bạn làm" (content cards, `p14-content-cards.md`). */
export type LeverExecutor = "juli" | "juli_with_photo" | "seller_center" | "juli_drafts";

/** §1 lever codes (seven change types, ADR-109 Amendment 1 d.3). */
export type LeverCode =
  | "cover_image"
  | "title"
  | "description"
  | "product_discount"
  | "flash_sale"
  | "shipping_discount"
  | "buy_more_save_more";

export interface CardKpi {
  readonly key: string;
  readonly label: string;
  readonly current: number | null;
  readonly target: number | null;
  readonly unit: "ratio" | "vnd";
}

export interface CardBeforeAfter {
  readonly field: string;
  readonly label: string;
  readonly before: string;
  readonly after: string;
}

/** §1 `GET /v1/demo/decisions` item → `recommendation.card`. */
export interface RecommendationCardPayload {
  readonly seller_sku: string | null;
  readonly seller_sku_more: number;
  readonly product_title: string | null;
  readonly workflow_label: string;
  readonly updated_at: string | null;
  readonly status: CardStatus;
  readonly main_kpi: CardKpi | null;
  readonly expected_gmv_per_month: number | null;
  readonly reason_short: string;
  readonly reason_full: string;
  readonly tiktok_codes: readonly string[];
  readonly lever: { readonly code: string; readonly label: string; readonly executor: LeverExecutor };
  readonly change_fields: readonly { readonly field: string; readonly label: string }[];
  readonly before_after: readonly CardBeforeAfter[];
  readonly gmv_method: string | null;
  /** P14-B (D24.6): the card's rank was weighted by the shop's results/reasons for the action. */
  readonly adjusted_by_history?: boolean;
  /** P14-E content cards only (`p14-content-cards.md` §1). */
  readonly content?: CardContentPayload | null;
}

/** P14-E `recommendation.card.content`. */
export interface CardContentPayload {
  readonly kind: "video" | "live";
  readonly action_label: string;
  readonly chip: string;
  readonly will_draft: readonly string[];
  readonly measure: string;
}

/** A decisions item as P10-A sends it (the `card` is additive). */
export type P10DecisionItem = DemoDecisionItem & {
  readonly recommendation: DemoDecisionItem["recommendation"] & {
    readonly card?: RecommendationCardPayload | null;
  };
};

/** §4/§5 `run.awaiting`. */
export type RunAwaiting = "photo" | "seller_action" | "content_choice" | "content_publish";

/**
 * A runs-list item as the backend sends it: `awaiting` (P10-B) and
 * `decision_id` (P10 integration — the card the run came from) are additive.
 */
export type QdRun = WorkflowRunListItem & {
  readonly awaiting?: RunAwaiting | null;
};

/** §4 photo checks. P10-B adds `heuristic` / `detail` per check (accepted deviation). */
export interface PhotoCheck {
  readonly key: string;
  readonly label: string;
  readonly ok: boolean;
  readonly heuristic?: boolean;
  readonly detail?: string;
}

/** `GET /v1/demo/runs/{id}` → `data` (P10-B; the fields Quyết định reads). */
export interface RunDetail {
  readonly id: string;
  readonly status: string;
  readonly awaiting: RunAwaiting | null;
  readonly awaiting_expires_at: string | null;
  readonly decision_id: string | null;
  readonly lever: { readonly code: string; readonly kind: string } | null;
  readonly photo: {
    readonly before_url: string | null;
    readonly after_url: string | null;
    readonly checks: readonly PhotoCheck[];
  } | null;
  readonly promotion: {
    readonly lever: string;
    readonly applied_at: string | null;
    readonly verify_attempts: number;
    readonly measurement_start: string | null;
  } | null;
  /** P14-E content runs only (`p14-content-cards.md` §2.1). */
  readonly content?: ContentRunDetail | null;
}

export type ContentStage = "drafting" | "choice" | "publish" | "measuring" | "declined" | "ended";

export interface ContentStep {
  readonly key: string;
  readonly label: string;
  readonly result: string | null;
  readonly at: string | null;
}

export interface ContentBlock {
  readonly key: string;
  readonly label: string;
  readonly text: string;
}

export interface ContentScript {
  readonly version: number;
  readonly title: string;
  readonly blocks: readonly ContentBlock[];
  readonly checks: readonly { readonly key: string; readonly label: string; readonly ok: boolean }[];
  readonly checks_line: string;
  readonly plain_text: string;
  readonly raw?: Record<string, unknown> | null;
}

export interface ContentWait {
  readonly title: string;
  readonly body: string;
  readonly done_label: string;
  readonly detect_what: string;
}

/** `GET /v1/demo/runs/{id}` → `data.content`. */
export interface ContentRunDetail {
  readonly kind: "video" | "live";
  readonly stage: ContentStage;
  readonly title: string;
  readonly headline: string;
  readonly steps: readonly ContentStep[];
  readonly script: ContentScript | null;
  readonly versions: number;
  readonly can_redraft: boolean;
  readonly chosen_version: number | null;
  readonly edited: boolean;
  readonly wait: ContentWait | null;
  readonly measure_body: string | null;
  readonly published_at: string | null;
  readonly detected: Record<string, unknown> | null;
}

/** §5 `GET /v1/demo/runs/{id}/instructions`. */
export interface SellerInstructions {
  readonly steps: readonly string[];
  readonly deep_link: string | null;
  readonly summary: string;
}

/** §6 measurement. */
export type MeasurementStage = "waiting" | "day7" | "final";
export type MeasurementTone = "ok" | "warn" | "muted";
export type FinalLabel = "dat" | "gan_dat" | "khong_dat" | "chua_ket_luan";
export type MeasureUnit = "ratio" | "vnd" | "count";

export interface MeasurementBand {
  readonly key: string;
  readonly label: string;
  readonly before: number | null;
  readonly band_pct: number;
  readonly low: number | null;
  readonly high: number | null;
  readonly unit: MeasureUnit;
}

export interface MeasurementRow {
  readonly key: string;
  readonly label: string;
  readonly before: number | null;
  readonly expected: string;
  readonly actual: number | null;
  readonly verdict: string;
  readonly tone: MeasurementTone;
}

export interface Measurement {
  readonly stage: MeasurementStage;
  readonly dates: { readonly day7: string; readonly day14: string };
  readonly target: {
    readonly label: string;
    readonly current: number | null;
    readonly target: number | null;
    readonly progress_from: number | null;
    readonly unit: MeasureUnit;
  };
  readonly expected_gmv_per_day: number | null;
  readonly bands: readonly MeasurementBand[];
  readonly rows: readonly MeasurementRow[];
  readonly day7: { readonly within_band: boolean | null; readonly question_id: string | null } | null;
  readonly final: {
    readonly label: FinalLabel;
    readonly gmv_actual_per_day: number | null;
    readonly pct_of_expected: number | null;
    readonly calibration: { readonly lever: string; readonly from: number; readonly to: number } | null;
  } | null;
}
