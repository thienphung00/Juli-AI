import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import {
  buildPlanImpact,
  type PlanComparisonContent,
  type PlanDecisionOptionGroup,
  type PlanReviewContent,
} from "../../plan-reviews";
import { describeOptionField } from "../../run-surface/option-diff";

import { getPlanCaveats } from "../../plan-caveats";
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

function requireInputField(fieldKey: string) {
  const inputsStage = getOptimizeProductReviewStages().find(
    (stage) => stage.stage === "inputs",
  );
  const field = inputsStage?.inputFields?.find(
    (candidate) => candidate.key === fieldKey,
  );

  if (!field) {
    throw new Error(
      `Missing optimize_product_2 field descriptor for ${fieldKey}`,
    );
  }

  return field;
}

/**
 * The review page's before/after (issue #1916): current values are the
 * listing facts the Situation already states ("Son môi số 12" at
 * 159.000 ₫); proposed values are the same prefills Juli pre-committed to
 * in the field descriptors — read from them here, so the comparison can
 * never drift from what approval actually submits. Field names resolve
 * through `describeOptionField`. Nothing is invented: the one field
 * without a known current value says so, and price states an explicit
 * keep rather than implying a change.
 */
function buildComparison(): PlanComparisonContent {
  const seoTitle = requireInputField("seo_title");
  const seoDescription = requireInputField("seo_description");
  const price = requireInputField("price");

  return {
    reason:
      "Tiêu đề hiện tại chưa đạt điểm chất lượng tối thiểu — tiêu đề và mô tả chuẩn SEO giúp sản phẩm được tìm thấy và nhấp xem nhiều hơn.",
    rows: [
      {
        fieldLabel: describeOptionField("seo_title"),
        current: "Son môi số 12",
        proposed: seoTitle.prefillValue ?? "",
      },
      {
        fieldLabel: describeOptionField("seo_description"),
        current: "Mô tả đang hiển thị trên tin đăng",
        proposed: seoDescription.prefillValue ?? "",
      },
      {
        fieldLabel: describeOptionField("price"),
        current: price.prefillValue ?? "",
        proposed: `Giữ nguyên ${price.prefillValue ?? ""}`,
      },
    ],
  };
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
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultOptimizeProductAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing `analyticsMetricKey`
    // binding — CTOR for optimize_product_2 (ADR-055 item 15). Nothing new is
    // mapped here, and no magnitude is projected (item 16).
    impact: buildPlanImpact(defaultOptimizeProductAnalyticsMetricKey),
    decision: {
      proposal:
        "Juli đề xuất cập nhật tiêu đề và mô tả SEO cho “Son môi số 12” để sản phẩm được nhấp xem nhiều hơn.",
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: optimizeProductFixture.reasoning,
      // Typed caveats, not the concatenated known-limits blob (ADR-055 item
      // 10). optimize_product_2 carries only the undefined-threshold class, so
      // nothing of it reaches the seller — which is the point.
      caveats: getPlanCaveats(OPTIMIZE_PRODUCT_WORKFLOW_KEY),
      recommendedOptions: {
        disclosureQuestion: "Juli đã cân nhắc phương án nào?",
        groups: buildRecommendedOptionGroups(),
      },
    },
    // Before/after with the reason beside it (issue #1916).
    comparison: buildComparison(),
    // No `details` key: optimize_product_2 has no branch discriminator, so
    // the Details section renders as nothing — never an empty stub.
  };
}
