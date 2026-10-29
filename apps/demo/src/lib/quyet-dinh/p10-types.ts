/**
 * Wire shapes of the P10 contract (`fasttrack/contracts/p10-quyet-dinh.md`),
 * field for field. P10-A / P10-B implement them in parallel; until they are
 * merged every field here is OPTIONAL on the wire and the UI degrades
 * (`card-model.ts` falls back to the P7-B diagnosis, Đo lường to the
 * completion date). Kept local to the demo app like `types.ts`.
 */

import type { DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";

/** §1 `recommendation.card.status`. P61-B: `simulated` = the run wrote to the sandbox, not the shop. */
export type CardStatus = "pending" | "running" | "applied" | "simulated" | "rejected" | "expired";

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
  /** P75c: the card's own TikTok product id (masked `an-product-…` for a reviewer). */
  readonly tiktok_product_id?: string | null;
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
  /** P17 (D26): a quick-scan card (`p17-onboarding-speed.md` §1); absent / null otherwise. */
  readonly quick_scan?: CardQuickScanPayload | null;
  /** P23 (D29.4): the product's one target metric. */
  readonly target_metric?: CardTargetMetric | null;
  /** P23 (D29.6): "Độ tin cậy: Cao / Vừa / Thấp". */
  readonly confidence?: CardConfidence | null;
  /** P23 (D29.7/D29.10): the band-based KPI; `display: "range"` for volatile products. */
  readonly kpi?: CardKpiTarget | null;
  /** P23 (D30.3): expected GMV as a range. */
  readonly gmv_estimate?: CardGmvEstimate | null;
  /** P23 (D29.4): other active cards of the same product + target metric. */
  readonly sibling_cards?: number | null;
  /** P30 (D34.8): one plain sentence about the card's group, once its day-14 verdict exists. */
  readonly group_result?: string | null;
}

export type CardTargetMetric = "ctr" | "ctor" | "aov" | "impressions";
export type CardConfidence = "high" | "medium" | "low";

/** P23 `recommendation.card.kpi` (values in the metric's unit: ratio / VND / count). */
export interface CardKpiTarget {
  readonly metric: CardTargetMetric;
  readonly current: number | null;
  readonly target: number | null;
  readonly target_min?: number | null;
  readonly target_max?: number | null;
  readonly display?: "point" | "range" | null;
  readonly band_pct?: number | null;
  readonly window_days?: 14 | 30 | 60 | number | null;
  readonly low_data?: boolean | null;
  /** D32: the channel the KPI is read and measured on; absent on cards from before D32. */
  readonly channel?: CardKpiChannel | null;
}

/** D32 `kpi.channel`: the lever's channel, or "total" (all channels, also the fallback). */
export type CardKpiChannel = "product_card" | "video" | "live" | "total";

export interface CardGmvEstimate {
  readonly per_month_min: number | null;
  readonly per_month_max: number | null;
}

/** P17 `recommendation.card.quick_scan`. */
export interface CardQuickScanPayload {
  readonly label: string;
  readonly confidence: string;
  readonly window_days: number;
  readonly basis: string;
}

/** P75: one video / LIVE session behind a content card (its evidence, best first). */
export interface CardContentSource {
  readonly video_id?: string | null;
  readonly live_id?: string | null;
  readonly title: string;
  readonly date: string | null;
}

/** P14-E `recommendation.card.content`. */
export interface CardContentPayload {
  readonly kind: "video" | "live";
  readonly action_label: string;
  readonly chip: string;
  readonly will_draft: readonly string[];
  readonly measure: string;
  /** P75 (additive): absent on a card stored before it. */
  readonly sources?: readonly CardContentSource[];
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
  /** Who set the band: the seller in Quy tắc, or Juli's default (D29.9). Absent on older payloads. */
  readonly source?: "seller" | "default";
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

/** P23 (D29.8): day-7 / day-14 verdict words. */
export interface MeasurementVerdict {
  readonly day7?: "rising" | "unclear" | null;
  readonly day14?: "met" | "partial" | "not_met" | null;
  /** D31.7: the day-14 target change against the pre/post bands combined; null: nothing new. */
  readonly strength?: "clear" | "likely" | "noise" | null;
  readonly affected_by_external_change?: boolean | null;
}

/** P23 (D30.4): a change made outside Juli that overlaps the measurement. */
export interface ExternalChange {
  readonly kind: string;
  readonly fields?: readonly string[] | null;
  readonly occurred_at: string | null;
  readonly source?: string | null;
}

export interface Measurement {
  readonly stage: MeasurementStage;
  readonly verdict?: MeasurementVerdict | null;
  readonly external_changes?: readonly ExternalChange[] | null;
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
