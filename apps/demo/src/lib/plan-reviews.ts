import {
  DELETE_ACTIVITY_WORKFLOW_KEY,
  getDeleteActivityPlanReview,
} from "./workflows/delete-activity";

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

export interface PlanDecisionContent {
  /** One pre-authored sentence stating what Juli proposes. */
  proposal: string;
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
    default:
      return null;
  }
}
