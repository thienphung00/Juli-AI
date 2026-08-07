import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import { getPlanCaveats } from "../../../plan-caveats";
import { getWorkflowPlanReview } from "../../../plan-reviews";
import {
  PREVENT_REFUND_WORKFLOW_KEY,
  buildPreventRefundReviewInputDefaults,
  defaultPreventRefundAnalyticsMetricKey,
} from "../review";
import { getPreventRefundPlanReview } from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === PREVENT_REFUND_WORKFLOW_KEY,
);

function collectPlanStrings(plan = getPreventRefundPlanReview()): string[] {
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

describe("getPreventRefundPlanReview", () => {
  it("returns the Situation → Decision → Details spine", () => {
    const plan = getPreventRefundPlanReview();

    expect(plan.workflowKey).toBe(PREVENT_REFUND_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
  });

  it("states the proposal in exactly one sentence", () => {
    const plan = getPreventRefundPlanReview();

    const sentences = plan.decision.proposal
      .split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);
    expect(sentences).toHaveLength(1);
  });

  it("collapses the seven known fields into one summary row with a count", () => {
    const plan = getPreventRefundPlanReview();

    expect(plan.situation.detailLines).toHaveLength(7);
    expect(plan.situation.summary).toContain("7 thông tin");
    expect(plan.situation.summary.split("\n")).toHaveLength(1);
  });

  it("phrases the situation disclosure as a question", () => {
    const plan = getPreventRefundPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
  });

  it("reads the known context out of the field data, not out of thin air", () => {
    const plan = getPreventRefundPlanReview();
    const defaults = buildPreventRefundReviewInputDefaults();
    const situation = plan.situation.detailLines.join(" ");

    expect(situation).toContain(defaults.aftersale_id);
    expect(situation).toContain(defaults.order_id);
    expect(plan.situation.summary).toContain(defaults.order_id);
  });

  /**
   * The calculated amount is a real figure the after-sales system already
   * produced — it is known context, never an estimate Juli invented.
   */
  it("shows the calculated amount as a seller-readable figure", () => {
    const plan = getPreventRefundPlanReview();
    const situation = plan.situation.detailLines.join(" ");

    expect(situation).toContain("185.000 ₫");
    for (const text of collectPlanStrings()) {
      expect(text).not.toMatch(/dự kiến|ước tính/i);
    }
  });

  it("pre-commits to the approve branch and offers the reject branch read-only", () => {
    const plan = getPreventRefundPlanReview();
    const defaults = buildPreventRefundReviewInputDefaults();
    const groups = plan.decision.recommendedOptions?.groups ?? [];

    expect(groups).toHaveLength(1);
    const proposed = groups[0].options.filter((option) => option.proposed);
    expect(proposed).toHaveLength(1);
    expect(proposed[0].value).toContain(defaults.seller_decision);
    expect(groups[0].options).toHaveLength(2);
  });

  it("gates the reject reason into Details — absent on the approve branch", () => {
    const approvePlan = getPreventRefundPlanReview();

    expect(approvePlan.details).toBeUndefined();
    for (const text of collectPlanStrings(approvePlan)) {
      expect(text).not.toMatch(/lý do từ chối/i);
    }
  });

  it("renders the reject reason in Details only on the reject branch", () => {
    const rejectPlan = getPreventRefundPlanReview({
      ...buildPreventRefundReviewInputDefaults(),
      seller_decision: "Từ chối",
      reject_reason: "Không đủ căn cứ hoàn tiền",
    });

    const details = (rejectPlan.details?.detailLines ?? []).join(" ");
    expect(details).toContain("Không đủ căn cứ hoàn tiền");
  });

  it("carries the workflow's reasoning behind the decision disclosure — never empty", () => {
    const plan = getPreventRefundPlanReview();

    expect(plan.decision.reasoning).toBe(fixture?.reasoning);
    expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
  });

  it("inherits its typed caveats from the shared classification", () => {
    const plan = getPreventRefundPlanReview();

    expect(plan.decision.caveats).toEqual(
      getPlanCaveats(PREVENT_REFUND_WORKFLOW_KEY),
    );
  });

  it("does not duplicate the class-D trust line in the decision copy", () => {
    const plan = getPreventRefundPlanReview();
    const trustLines = getPlanCaveats(PREVENT_REFUND_WORKFLOW_KEY).filter(
      (caveat) => caveat.caveatClass === "reassurance",
    );

    expect(trustLines.length).toBeGreaterThan(0);
    for (const caveat of trustLines) {
      expect(plan.decision.proposal).not.toContain(caveat.text);
    }
    expect(plan.decision.proposal).not.toMatch(/Juli không tự/i);
  });

  it("ties the impact block and the situation deep link to the same Main KPI — GMV", () => {
    const plan = getPreventRefundPlanReview();

    expect(defaultPreventRefundAnalyticsMetricKey).toBe("gmv-tiktok");
    expect(plan.impact.metricKey).toBe("gmv-tiktok");
    expect(plan.situation.analyticsMetricHref).toBe("/analytics/gmv-tiktok");
  });

  it("carries a directional goal and never a projected magnitude", () => {
    const plan = getPreventRefundPlanReview();

    expect(plan.impact.directionalGoal).toMatch(/^Mục tiêu:/);
    expect(plan.impact.directionalGoal).not.toMatch(/\d/);
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
    expect(getWorkflowPlanReview(PREVENT_REFUND_WORKFLOW_KEY)?.workflowKey).toBe(
      PREVENT_REFUND_WORKFLOW_KEY,
    );
  });
});
