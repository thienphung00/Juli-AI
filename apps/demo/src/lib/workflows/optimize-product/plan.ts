import type {
  PlanDecisionOptionGroup,
  PlanReviewContent,
} from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  defaultOptimizeProductAnalyticsMetricKey,
  getOptimizeProductReviewStages,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === OPTIMIZE_PRODUCT_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing optimize_product_2 recommendation fixture");
}

const optimizeProductFixture = fixtureEntry;

/** The two seller decisions, in traversal order. */
const DECISION_FIELD_KEYS = ["seo_title", "seo_description"] as const;

/**
 * The recommended option groups come straight from the field descriptors —
 * the same option lists the field-kind work introduced — so the plan never
 * drifts from the canonical values. Juli's pre-committed value is the field's
 * prefill.
 */
function buildRecommendedOptionGroups(): PlanDecisionOptionGroup[] {
  const inputsStage = getOptimizeProductReviewStages().find(
    (stage) => stage.stage === "inputs",
  );

  return DECISION_FIELD_KEYS.map((fieldKey) => {
    const field = inputsStage?.inputFields?.find(
      (candidate) => candidate.key === fieldKey,
    );

    if (!field?.options?.length) {
      throw new Error(
        `Missing recommended options for optimize_product_2 field ${fieldKey}`,
      );
    }

    return {
      label: field.label,
      options: field.options.map((option) => ({
        value: option.value,
        proposed: option.value === field.prefillValue || undefined,
      })),
    };
  });
}

/**
 * Situation → Decision → Details plan review for `optimize_product_2`
 * (ADR-055 items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing). The workflow has three known fields collapsing
 * into one summary row, two seller decisions carrying recommended options,
 * and no branch discriminator — so `details` is deliberately absent. The
 * Analytics deep link lives behind the Situation expansion; there is no
 * separate evidence step.
 */
export function getOptimizeProductPlanReview(): PlanReviewContent {
  return {
    workflowKey: OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    title: optimizeProductFixture.title,
    situation: {
      summary: "Sản phẩm “Son môi số 12” · 3 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        "Juli đang theo dõi sản phẩm PRD-88421 — “Son môi số 12” trên shop.",
        "Giá bán giữ ở 159.000 ₫, trong giới hạn lợi nhuận shop đã cấu hình.",
        "Ảnh sản phẩm và tệp hỗ trợ giữ nguyên — Juli chỉ thay khi shop yêu cầu.",
      ],
      analyticsMetricHref: `/analytics/${defaultOptimizeProductAnalyticsMetricKey}`,
    },
    decision: {
      proposal:
        "Juli đề xuất cập nhật tiêu đề và mô tả SEO cho “Son môi số 12” để sản phẩm được nhấp xem nhiều hơn.",
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: optimizeProductFixture.reasoning,
      recommendedOptions: {
        disclosureQuestion: "Juli đã cân nhắc phương án nào?",
        groups: buildRecommendedOptionGroups(),
      },
    },
    // No `details` key: optimize_product_2 has no branch discriminator, so
    // the Details section renders as nothing — never an empty stub.
  };
}
