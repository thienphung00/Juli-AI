import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import { getWorkflowPlanReview } from "../../../plan-reviews";
import {
  REPLENISH_INVENTORY_WORKFLOW_KEY,
  buildReplenishInventoryReviewInputDefaults,
  defaultReplenishInventoryAnalyticsMetricKey,
  getReplenishInventoryReviewStages,
} from "../review";
import { createReplenishInventoryTimeline } from "../execution";
import { getReplenishInventoryPlanReview } from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === REPLENISH_INVENTORY_WORKFLOW_KEY,
);

function collectPlanStrings(): string[] {
  const plan = getReplenishInventoryPlanReview();
  const optionStrings = (plan.decision.recommendedOptions?.groups ?? []).flatMap(
    (group) => [group.label, ...group.options.map((option) => option.value)],
  );
  return [
    plan.title,
    plan.decision.proposal,
    plan.decision.reasoning,
    plan.decision.recommendedOptions?.disclosureQuestion ?? "",
    plan.situation.summary,
    plan.situation.disclosureQuestion,
    ...plan.situation.detailLines,
    ...(plan.details?.detailLines ?? []),
    ...optionStrings,
  ];
}

describe("getReplenishInventoryPlanReview", () => {
  it("returns the Situation → Decision spine with no Details section", () => {
    const plan = getReplenishInventoryPlanReview();

    expect(plan.workflowKey).toBe(REPLENISH_INVENTORY_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
    // Both remaining seller decisions (reorder quantity, supplier path) fit
    // the Decision section's 1–2 items, so Details is absent — ADR-055 item 8.
    expect(plan.details).toBeUndefined();
  });

  it("states the proposal in exactly one sentence", () => {
    const plan = getReplenishInventoryPlanReview();

    const sentences = plan.decision.proposal
      .split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);
    expect(sentences).toHaveLength(1);
  });

  it("collapses the three known fields into one summary row with a count", () => {
    const plan = getReplenishInventoryPlanReview();

    expect(plan.situation.summary).toContain("3 thông tin");
    expect(plan.situation.detailLines).toHaveLength(3);
  });

  it("phrases the situation disclosure as a question", () => {
    const plan = getReplenishInventoryPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
  });

  it("carries the workflow's reasoning behind the decision disclosure — never empty", () => {
    const plan = getReplenishInventoryPlanReview();

    expect(plan.decision.reasoning).toBe(fixture?.reasoning);
    expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
  });

  it("ties the impact block and the situation deep link to the same Main KPI — GMV", () => {
    const plan = getReplenishInventoryPlanReview();

    // ADR-055 item 15 lists replenish_inventory_3 under GMV.
    expect(defaultReplenishInventoryAnalyticsMetricKey).toBe("gmv-tiktok");
    expect(plan.impact.metricKey).toBe("gmv-tiktok");
    expect(plan.situation.analyticsMetricHref).toBe("/analytics/gmv-tiktok");
  });

  it("carries a directional goal and never a projected magnitude", () => {
    const plan = getReplenishInventoryPlanReview();

    expect(plan.impact.directionalGoal).toMatch(/^Mục tiêu:/);
    expect(plan.impact.directionalGoal).not.toMatch(/\d/);
    // No projected magnitude anywhere: no currency amount reaches the card.
    for (const text of collectPlanStrings()) {
      expect(text).not.toMatch(/₫/);
    }
  });

  it("does not carry the risks copy anywhere in the plan", () => {
    expect(fixture?.risks).toBeTruthy();
    for (const text of collectPlanStrings()) {
      expect(text).not.toContain(fixture!.risks);
    }
  });

  it("keeps every plan string free of system vocabulary", () => {
    for (const text of collectPlanStrings()) {
      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(text).not.toMatch(pattern);
      }
    }
  });

  it("is served by the plan review registry", () => {
    expect(
      getWorkflowPlanReview(REPLENISH_INVENTORY_WORKFLOW_KEY)?.workflowKey,
    ).toBe(REPLENISH_INVENTORY_WORKFLOW_KEY);
  });
});

/**
 * Post-execution field removal (issue #766, ADR-055 Context). `received_quantity`
 * is "Số lượng nhận hàng thực tế (sau giao)" — an outcome that only exists after
 * delivery. No seller can answer it at approve time, so it is gone from the
 * approval flow entirely: not hidden, not disabled, not optional.
 */
describe("replenish_inventory_3 post-execution field removal", () => {
  it("does not ask for the post-delivery received quantity anywhere in the plan", () => {
    for (const text of collectPlanStrings()) {
      expect(text).not.toMatch(/nhận hàng thực tế/i);
      expect(text).not.toMatch(/sau giao/i);
    }
  });

  it("removes received_quantity from the review input defaults", () => {
    const defaults = buildReplenishInventoryReviewInputDefaults();

    expect(Object.hasOwn(defaults, "received_quantity")).toBe(false);
  });

  it("removes received_quantity from the inputs stage field descriptors", () => {
    const inputs = getReplenishInventoryReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    const fieldKeys = inputs?.inputFields?.map((field) => field.key) ?? [];
    expect(fieldKeys).not.toContain("received_quantity");
    // The three known fields plus the two remaining seller decisions.
    expect(fieldKeys).toEqual([
      "sku_id",
      "current_stock",
      "warehouse_id",
      "reorder_quantity",
      "external_path",
    ]);
  });

  it("still starts and advances execution without a value supplied at approve time", () => {
    const timeline = createReplenishInventoryTimeline();

    expect(timeline.length).toBeGreaterThan(1);
    expect(timeline[0]?.status).toBe("pending");
    // Nothing in the run depends on a value collected at approve time.
    const defaults = buildReplenishInventoryReviewInputDefaults();
    expect(Object.values(defaults).every((value) => value !== "")).toBe(true);
  });
});
