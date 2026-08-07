import {
  DELETE_ACTIVITY_WORKFLOW_KEY,
  getDeleteActivityPlanReview,
} from "./workflows/delete-activity";
import {
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  getOptimizeProductPlanReview,
} from "./workflows/optimize-product";

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

export interface PlanDetailsContent {
  /** Branch-gated execution specifics for the chosen branch. */
  detailLines: string[];
}

export interface PlanReviewContent {
  workflowKey: string;
  title: string;
  situation: PlanSituationContent;
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
    case DELETE_ACTIVITY_WORKFLOW_KEY:
      return getDeleteActivityPlanReview();
    case OPTIMIZE_PRODUCT_WORKFLOW_KEY:
      return getOptimizeProductPlanReview();
    default:
      return null;
  }
}
