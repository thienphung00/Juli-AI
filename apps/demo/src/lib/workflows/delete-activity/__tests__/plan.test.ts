import { describe, expect, it } from "vitest";

import {
  getPlanCaveats,
  getReassuranceCaveats,
} from "../../../plan-caveats";
import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import { getWorkflowPlanReview } from "../../../plan-reviews";
import { DELETE_ACTIVITY_WORKFLOW_KEY } from "../review";
import { getDeleteActivityPlanReview } from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === DELETE_ACTIVITY_WORKFLOW_KEY,
);

function collectPlanStrings(): string[] {
  const plan = getDeleteActivityPlanReview();
  return [
    plan.title,
    plan.decision.proposal,
    plan.decision.reasoning,
    plan.situation.summary,
    plan.situation.disclosureQuestion,
    ...plan.situation.detailLines,
    ...plan.decision.caveats.map((caveat) => caveat.text),
  ];
}

describe("getDeleteActivityPlanReview", () => {
  it("returns the Situation → Decision spine with no Details section", () => {
    const plan = getDeleteActivityPlanReview();

    expect(plan.workflowKey).toBe(DELETE_ACTIVITY_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
    // Details is absent — not an empty stub.
    expect(plan.details).toBeUndefined();
  });

  it("states the proposal in exactly one sentence", () => {
    const plan = getDeleteActivityPlanReview();

    const sentences = plan.decision.proposal
      .split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);
    expect(sentences).toHaveLength(1);
  });

  it("collapses the single known field into a count, not labelled read-only fields", () => {
    const plan = getDeleteActivityPlanReview();

    expect(plan.situation.summary).toContain("1 thông tin");
    expect(plan.situation.detailLines).toHaveLength(1);
  });

  it("phrases the situation disclosure as a question", () => {
    const plan = getDeleteActivityPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
  });

  it("carries the workflow's reasoning behind the decision disclosure — never empty", () => {
    const plan = getDeleteActivityPlanReview();

    expect(plan.decision.reasoning).toBe(fixture?.reasoning);
    expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
  });

  it("carries typed caveats, including the promotion-search gap shown when asked", () => {
    const plan = getDeleteActivityPlanReview();

    expect(plan.decision.caveats).toEqual(
      getPlanCaveats(DELETE_ACTIVITY_WORKFLOW_KEY),
    );
    expect(
      plan.decision.caveats.map((caveat) => caveat.caveatClass),
    ).toEqual([
      "threshold-undefined",
      "feature-unavailable",
      "fulfilment-unsupported",
    ]);
    // No no-act promise in this workflow's known limits — no trust line.
    expect(getReassuranceCaveats(DELETE_ACTIVITY_WORKFLOW_KEY)).toHaveLength(0);
  });

  it("does not carry the concatenated known-limits blob anywhere in the plan", () => {
    expect(fixture?.knownLimits).toBeTruthy();
    for (const text of collectPlanStrings()) {
      expect(text).not.toBe(fixture!.knownLimits);
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

  it("links the situation expansion to the tied CTOR metric", () => {
    const plan = getDeleteActivityPlanReview();

    expect(plan.situation.analyticsMetricHref).toBe("/analytics/ctor");
  });
});

describe("getWorkflowPlanReview routing", () => {
  it("returns the plan for delete_activity_7b and keeps unmigrated workflows off the spine", () => {
    expect(getWorkflowPlanReview(DELETE_ACTIVITY_WORKFLOW_KEY)).not.toBeNull();

    // Migrated by later rollout slices, so no longer expected to be null:
    // optimize_product_2 (#765), replenish_inventory_3 / clear_excess_4 (#766),
    // create_activity_7a / update_activity_7c (#768), and the Returns trio
    // prevent_cancellation_8a / prevent_return_8b / prevent_refund_8c (#769).
    for (const otherKey of ["create_hero_product_1", "process_order_5"]) {
      expect(getWorkflowPlanReview(otherKey)).toBeNull();
    }
  });
});
