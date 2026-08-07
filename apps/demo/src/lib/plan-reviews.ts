import type { PlanCaveat } from "./plan-caveats";

import {
  IMPACT_METRIC_KEYS,
  type ImpactMetricKey,
} from "./analytics/main-kpis";
import {
  CREATE_ACTIVITY_WORKFLOW_KEY,
  getCreateActivityPlanReview,
} from "./workflows/create-activity";
import {
  DELETE_ACTIVITY_WORKFLOW_KEY,
  getDeleteActivityPlanReview,
} from "./workflows/delete-activity";
import {
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  getOptimizeProductPlanReview,
} from "./workflows/optimize-product";
import {
  UPDATE_ACTIVITY_WORKFLOW_KEY,
  getUpdateActivityPlanReview,
} from "./workflows/update-activity";
import {
  REPLENISH_INVENTORY_WORKFLOW_KEY,
  getReplenishInventoryPlanReview,
} from "./workflows/replenish-inventory";
import {
  CLEAR_EXCESS_WORKFLOW_KEY,
  getClearExcessPlanReview,
} from "./workflows/clear-excess";
import {
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  getPreventCancellationPlanReview,
} from "./workflows/prevent-cancellation";
import {
  PREVENT_RETURN_WORKFLOW_KEY,
  getPreventReturnPlanReview,
} from "./workflows/prevent-return";
import {
  PREVENT_REFUND_WORKFLOW_KEY,
  getPreventRefundPlanReview,
} from "./workflows/prevent-refund";

/**
 * Decision plan review — the Situation → Decision → Details spine (ADR-055
 * items 1, 8, 13). Content is rule-based and pre-authored; there is no LLM
 * layer. Workflows without a plan review here keep the five-stage review.
 */

export interface PlanSituationContent {
  /**
   * One summary line following the summarise-don't-enumerate pattern
   * (ADR-055 item 13): identity plus a count — never labelled read-only
   * fields.
   */
  summary: string;
  /** Disclosure label, phrased as a question — never a noun. */
  disclosureQuestion: string;
  /** Seller-language sentences revealed on expansion, below the summary. */
  detailLines: string[];
  /** The tied Main KPI deep link, living behind the Situation expansion. */
  analyticsMetricHref: string;
}

/**
 * Shared label for the reasoning disclosure on every plan review — phrased as
 * a question, never a noun (ADR-055 items 3, 13). One label across all
 * workflows so the seller learns the pattern once.
 */
export const PLAN_REASONING_DISCLOSURE_QUESTION =
  "Vì sao Juli đề xuất điều này?";

export interface PlanDecisionRecommendedOption {
  /** Seller-language option text. */
  value: string;
  /** True on the one option Juli pre-committed to (ADR-055 item 2). */
  proposed?: boolean;
}

export interface PlanDecisionOptionGroup {
  /** Seller-language label naming what the option list decides. */
  label: string;
  /** Recommended options, including the proposed value. */
  options: PlanDecisionRecommendedOption[];
}

export interface PlanDecisionContent {
  /** One pre-authored sentence stating what Juli proposes. */
  proposal: string;
  /**
   * Why Juli proposes this — one short pre-authored seller sentence, revealed
   * by the question-labelled disclosure inside the Decision section. REQUIRED:
   * the expansion is a reasoning container, not a limits container (ADR-055
   * item 11), and it must never open onto nothing. Source it from the shared
   * fixture table's `reasoning`, which is populated for all eleven workflows;
   * the card sanitizes it through the seller-copy sanitizer at render.
   */
  reasoning: string;
  /**
   * The workflow's caveats, typed by class (ADR-055 item 10). REQUIRED: the
   * card applies one presentation rule per class — hidden, inside the
   * reasoning expansion, or resting as a trust line — and never inspects the
   * text, so an untyped caveat has nowhere to go. Source it from
   * `getPlanCaveats(workflowKey)`, which classifies all eleven workflows;
   * the card sanitizes each rendered string at render.
   */
  caveats: readonly PlanCaveat[];
  /**
   * Recommended options resting behind a question-phrased disclosure.
   * Read-only: the editing interaction is out of scope (ADR-055 item 14).
   * Absent when a workflow's decision carries no option list.
   */
  recommendedOptions?: {
    /** Disclosure label, phrased as a question — never a noun. */
    disclosureQuestion: string;
    groups: PlanDecisionOptionGroup[];
  };
}

/**
 * Directional goals, one per tie-able Main KPI (ADR-055 item 15).
 *
 * A goal states a *direction* and names the metric in seller language. It
 * carries no magnitude and no number of any kind: ADR-055 item 16 bars a
 * projected impact on three independent grounds, and PRD user story 22 holds
 * Juli to never quoting an amount it cannot stand behind.
 *
 * Authored once here, shared by every workflow tied to the same KPI, so two
 * workflows on one metric can never phrase the goal differently.
 */
export const IMPACT_DIRECTIONAL_GOALS: Record<ImpactMetricKey, string> = {
  "gmv-tiktok": "Mục tiêu: tăng doanh thu bán hàng trên TikTok Shop",
  aov: "Mục tiêu: tăng giá trị trung bình mỗi đơn hàng",
  ctor: "Mục tiêu: tăng tỷ lệ khách xem chuyển thành đơn hàng",
  "cancellation-rate": "Mục tiêu: giảm tỷ lệ đơn hàng bị hủy",
};

export interface PlanImpactContent {
  /**
   * The Main KPI this workflow is already tied to. Read the workflow's
   * existing `analyticsMetricKey` binding — never author a new one, and never
   * map anything onto LIVE hours (ADR-055 item 15).
   */
  metricKey: ImpactMetricKey;
  /**
   * The directional goal shown under the KPI's real value. Always
   * `IMPACT_DIRECTIONAL_GOALS[metricKey]` — build it with `buildPlanImpact`
   * rather than writing a per-workflow sentence.
   */
  directionalGoal: string;
}

/**
 * Tie a plan review to its workflow's existing Main KPI.
 *
 * This is the whole authoring surface for the impact block: a rollout slice
 * passes the workflow's `analyticsMetricKey`, and the block reads the real
 * current value, trend and Analytics deep link from there. There is no
 * per-workflow number to write, by design.
 */
export function buildPlanImpact(
  metricKey: ImpactMetricKey,
): PlanImpactContent {
  return { metricKey, directionalGoal: IMPACT_DIRECTIONAL_GOALS[metricKey] };
}

export { IMPACT_METRIC_KEYS };
export type { ImpactMetricKey };

export interface PlanDetailsContent {
  /** Branch-gated execution specifics for the chosen branch. */
  detailLines: string[];
}

export interface PlanReviewContent {
  workflowKey: string;
  title: string;
  situation: PlanSituationContent;
  /**
   * The card's centre of gravity: the tied Main KPI's real current value and
   * trend, plus a directional goal (ADR-055 items 15–17). Required — every
   * workflow is already tied to a KPI, so there is no plan without one.
   */
  impact: PlanImpactContent;
  decision: PlanDecisionContent;
  /**
   * Absent (undefined) when the workflow has no branch-gated detail —
   * the section then renders as nothing, never as an empty stub.
   */
  details?: PlanDetailsContent;
}

export function getWorkflowPlanReview(
  workflowKey: string,
): PlanReviewContent | null {
  switch (workflowKey) {
    case CREATE_ACTIVITY_WORKFLOW_KEY:
      return getCreateActivityPlanReview();
    case DELETE_ACTIVITY_WORKFLOW_KEY:
      return getDeleteActivityPlanReview();
    case OPTIMIZE_PRODUCT_WORKFLOW_KEY:
      return getOptimizeProductPlanReview();
    case UPDATE_ACTIVITY_WORKFLOW_KEY:
      return getUpdateActivityPlanReview();
    case REPLENISH_INVENTORY_WORKFLOW_KEY:
      return getReplenishInventoryPlanReview();
    case CLEAR_EXCESS_WORKFLOW_KEY:
      return getClearExcessPlanReview();
    case PREVENT_CANCELLATION_WORKFLOW_KEY:
      return getPreventCancellationPlanReview();
    case PREVENT_RETURN_WORKFLOW_KEY:
      return getPreventReturnPlanReview();
    case PREVENT_REFUND_WORKFLOW_KEY:
      return getPreventRefundPlanReview();
    default:
      return null;
  }
}
