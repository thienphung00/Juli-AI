import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import { buildPlanImpact, type PlanReviewContent } from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  UPDATE_ACTIVITY_WORKFLOW_KEY,
  defaultUpdateActivityAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === UPDATE_ACTIVITY_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing update_activity_7c recommendation fixture");
}

const updateActivityFixture = fixtureEntry;

/**
 * Situation → Decision → Details plan review for `update_activity_7c`
 * (ADR-055 items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing). Two known fields — the tracked programme and the
 * product currently taking part — collapse into one Situation summary row. Of
 * the four decided fields the Decision sentence carries only the adjustment
 * Juli proposes; the promotion kind, the product and the new window are
 * branch-gated into Details rather than stacked into the Decision.
 *
 * The promotion-search gap is deliberately not rendered here — its
 * presentation is owned by the typed-caveat slice (ADR-055 item 10, class C).
 */
export function getUpdateActivityPlanReview(): PlanReviewContent {
  return {
    workflowKey: UPDATE_ACTIVITY_WORKFLOW_KEY,
    title: updateActivityFixture.title,
    situation: {
      summary: "Chương trình “Flash Sale chăm sóc da” · 2 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        "Juli đang theo dõi chương trình ACT-8842 — “Flash Sale chăm sóc da”, hiện đang chạy trên shop.",
        "Sản phẩm đang tham gia chương trình: PRD-77201 — Serum dưỡng ẩm, giá gốc đã được đối chiếu.",
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultUpdateActivityAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing `analyticsMetricKey`
    // binding — CTOR for the three promotion workflows (ADR-055 item 15).
    // Nothing new is mapped here, and no magnitude is projected (item 16).
    impact: buildPlanImpact(defaultUpdateActivityAnalyticsMetricKey),
    decision: {
      proposal:
        "Juli đề xuất cập nhật chương trình “Flash Sale chăm sóc da” sang mức giảm 25% từ giá gốc.",
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: updateActivityFixture.reasoning,
    },
    details: {
      detailLines: [
        "Loại khuyến mãi giữ nguyên là Flash Sale, áp dụng cho PRD-77201 — Serum dưỡng ẩm.",
        "Cửa sổ khuyến mãi mới chạy từ ngày 12/08/2026 đến hết ngày 19/08/2026.",
      ],
    },
  };
}
