import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import { buildPlanImpact, type PlanReviewContent } from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  CREATE_ACTIVITY_WORKFLOW_KEY,
  defaultCreateActivityAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === CREATE_ACTIVITY_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing create_activity_7a recommendation fixture");
}

const createActivityFixture = fixtureEntry;

/**
 * Situation → Decision → Details plan review for `create_activity_7a`
 * (ADR-055 items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing). The single known field — the pre-selected
 * product group — collapses into the Situation summary row. Of the four
 * decided fields the Decision sentence carries only the branch discriminator
 * and the discount; the participating products and the promotion window are
 * branch-gated into Details rather than stacked into the Decision.
 *
 * The promotion-search gap is deliberately not rendered here — its
 * presentation is owned by the typed-caveat slice (ADR-055 item 10, class C).
 */
export function getCreateActivityPlanReview(): PlanReviewContent {
  return {
    workflowKey: CREATE_ACTIVITY_WORKFLOW_KEY,
    title: createActivityFixture.title,
    situation: {
      summary: "Nhóm sản phẩm chăm sóc da · 1 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        "Juli đã chọn sẵn 2 sản phẩm chăm sóc da đủ điều kiện: PRD-77201 — Serum dưỡng ẩm và PRD-77202 — Kem chống nắng SPF50.",
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultCreateActivityAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing `analyticsMetricKey`
    // binding — CTOR for the three promotion workflows (ADR-055 item 15).
    // Nothing new is mapped here, and no magnitude is projected (item 16).
    impact: buildPlanImpact(defaultCreateActivityAnalyticsMetricKey),
    decision: {
      proposal:
        "Juli đề xuất tạo chương trình giảm giá trực tiếp 15% cho nhóm chăm sóc da để kích thích doanh số tuần này.",
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: createActivityFixture.reasoning,
    },
    details: {
      detailLines: [
        "Giảm 15% từ giá gốc, áp dụng cho PRD-77201 — Serum dưỡng ẩm và PRD-77202 — Kem chống nắng SPF50.",
        "Chương trình chạy từ ngày 10/08/2026 đến hết ngày 24/08/2026.",
      ],
    },
  };
}
