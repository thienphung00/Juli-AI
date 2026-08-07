import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import { buildPlanImpact, type PlanReviewContent } from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  REPLENISH_INVENTORY_WORKFLOW_KEY,
  buildReplenishInventoryReviewInputDefaults,
  defaultReplenishInventoryAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === REPLENISH_INVENTORY_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing replenish_inventory_3 recommendation fixture");
}

const replenishFixture = fixtureEntry;

/**
 * Situation → Decision → Details plan review for `replenish_inventory_3`
 * (ADR-055 items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing).
 *
 * Three known fields (SKU, current stock, shipping warehouse) collapse into
 * one summary row. Two seller decisions remain — the reorder quantity and the
 * supplier path — and both fit the Decision section's 1–2 items, so `details`
 * is deliberately absent.
 *
 * The post-execution `received_quantity` field is gone from the approval flow
 * entirely (issue #766): it asks for a quantity that only exists after
 * delivery. Nothing here replaces it as body copy.
 *
 * The Analytics deep link lives behind the Situation expansion; there is no
 * separate evidence step.
 */
export function getReplenishInventoryPlanReview(): PlanReviewContent {
  const defaults = buildReplenishInventoryReviewInputDefaults();

  return {
    workflowKey: REPLENISH_INVENTORY_WORKFLOW_KEY,
    title: replenishFixture.title,
    situation: {
      summary: "Sản phẩm “Kem chống nắng SPF50” · 3 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        "Juli đang theo dõi SKU-SPF50-001 — “Kem chống nắng SPF50” trên shop.",
        "Tồn kho còn 48 đơn vị, đủ cho khoảng 4 ngày bán theo tốc độ hiện tại.",
        "Hàng xuất từ kho HCM (WH-HCM-01) đang gán cho sản phẩm này.",
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultReplenishInventoryAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing `analyticsMetricKey`
    // binding — GMV for replenish_inventory_3 (ADR-055 item 15). Nothing new
    // is mapped here, and no magnitude is projected (item 16).
    impact: buildPlanImpact(defaultReplenishInventoryAnalyticsMetricKey),
    decision: {
      proposal: `Juli đề xuất đặt thêm ${defaults.reorder_quantity} đơn vị “Kem chống nắng SPF50” qua nhà cung cấp Hóa Mỹ Phẩm để shop không hết hàng trong vài ngày tới.`,
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: replenishFixture.reasoning,
    },
    // No `details` key: both remaining decisions rest in the Decision section,
    // so the Details section renders as nothing — never an empty stub.
  };
}
