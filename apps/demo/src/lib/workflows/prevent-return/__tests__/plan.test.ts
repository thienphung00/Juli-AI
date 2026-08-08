import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import { getPlanCaveats } from "../../../plan-caveats";
import { getWorkflowPlanReview } from "../../../plan-reviews";
import {
  PREVENT_RETURN_WORKFLOW_KEY,
  buildPreventReturnReviewInputDefaults,
  defaultPreventReturnAnalyticsMetricKey,
  getPreventReturnReviewStages,
} from "../review";
import { getPreventReturnPlanReview } from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === PREVENT_RETURN_WORKFLOW_KEY,
);

function collectPlanStrings(plan = getPreventReturnPlanReview()): string[] {
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

/**
 * Post-execution field removal (ADR-055 Context; issue #769).
 *
 * `resellable_quantity` was labelled "Số lượng còn bán được (sau kiểm tra)" —
 * the quantity still sellable **after inspection**. No seller can answer it at
 * approve time, so it is removed from the approval flow entirely: not hidden,
 * not disabled, not optional.
 */
describe("prevent_return_8b post-execution field removal", () => {
  it("drops resellable_quantity from the approval input defaults", () => {
    expect(buildPreventReturnReviewInputDefaults()).not.toHaveProperty(
      "resellable_quantity",
    );
  });

  it("drops resellable_quantity from the inputs stage entirely", () => {
    const inputsStage = getPreventReturnReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    expect(inputsStage).toBeDefined();
    const fieldKeys = (inputsStage?.inputFields ?? []).map((field) => field.key);
    expect(fieldKeys).not.toContain("resellable_quantity");
    // Not merely hidden or disabled — there is no field object left at all.
    expect(
      (inputsStage?.inputFields ?? []).some((field) =>
        /còn bán được/i.test(field.label),
      ),
    ).toBe(false);
    // The stage body no longer asks for it either.
    expect(inputsStage?.body ?? "").not.toMatch(/còn bán được/i);
  });

  it("keeps the approval flow able to start execution without it", () => {
    const stages = getPreventReturnReviewStages();

    expect(stages.map((stage) => stage.stage)).toContain("approve");
    expect(
      (stages.find((stage) => stage.stage === "inputs")?.inputFields ?? [])
        .length,
    ).toBeGreaterThan(0);
  });

  it("never mentions the removed field anywhere on the plan", () => {
    for (const text of collectPlanStrings()) {
      expect(text).not.toMatch(/còn bán được/i);
    }
  });
});

describe("getPreventReturnPlanReview", () => {
  it("returns the Situation → Decision → Details spine", () => {
    const plan = getPreventReturnPlanReview();

    expect(plan.workflowKey).toBe(PREVENT_RETURN_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
  });

  it("states the proposal in exactly one sentence", () => {
    const plan = getPreventReturnPlanReview();

    const sentences = plan.decision.proposal
      .split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);
    expect(sentences).toHaveLength(1);
  });

  it("collapses the seven known fields into one summary row with a count", () => {
    const plan = getPreventReturnPlanReview();

    expect(plan.situation.detailLines).toHaveLength(7);
    expect(plan.situation.summary).toContain("7 thông tin");
    // Seven fields, one line — the heaviest known-field load in the set.
    expect(plan.situation.summary.split("\n")).toHaveLength(1);
  });

  it("phrases the situation disclosure as a question", () => {
    const plan = getPreventReturnPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
  });

  it("reads the known context out of the field data, not out of thin air", () => {
    const plan = getPreventReturnPlanReview();
    const defaults = buildPreventReturnReviewInputDefaults();
    const situation = plan.situation.detailLines.join(" ");

    expect(situation).toContain(defaults.return_id);
    expect(situation).toContain(defaults.order_id);
    expect(plan.situation.summary).toContain(defaults.order_id);
  });

  it("pre-commits to the approve branch and offers the reject branch read-only", () => {
    const plan = getPreventReturnPlanReview();
    const defaults = buildPreventReturnReviewInputDefaults();
    const groups = plan.decision.recommendedOptions?.groups ?? [];

    expect(groups).toHaveLength(1);
    const proposed = groups[0].options.filter((option) => option.proposed);
    expect(proposed).toHaveLength(1);
    expect(proposed[0].value).toContain(defaults.seller_decision);
    expect(groups[0].options).toHaveLength(2);
  });

  it("renders only the chosen branch — no reject reason on approve", () => {
    const approvePlan = getPreventReturnPlanReview();

    expect(approvePlan.details).toBeUndefined();
    for (const text of collectPlanStrings(approvePlan)) {
      expect(text).not.toMatch(/lý do từ chối/i);
    }
  });

  it("renders the reject reason in Details only on the reject branch", () => {
    const rejectPlan = getPreventReturnPlanReview({
      ...buildPreventReturnReviewInputDefaults(),
      seller_decision: "Từ chối",
      reject_reason: "Hàng đã qua sử dụng",
    });

    const details = (rejectPlan.details?.detailLines ?? []).join(" ");
    expect(details).toContain("Hàng đã qua sử dụng");
  });

  it("carries the workflow's reasoning behind the decision disclosure — never empty", () => {
    const plan = getPreventReturnPlanReview();

    expect(plan.decision.reasoning).toBe(fixture?.reasoning);
    expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
  });

  it("inherits its typed caveats from the shared classification", () => {
    const plan = getPreventReturnPlanReview();

    expect(plan.decision.caveats).toEqual(
      getPlanCaveats(PREVENT_RETURN_WORKFLOW_KEY),
    );
  });

  it("does not duplicate the class-D trust line in the decision copy", () => {
    const plan = getPreventReturnPlanReview();
    const trustLines = getPlanCaveats(PREVENT_RETURN_WORKFLOW_KEY).filter(
      (caveat) => caveat.caveatClass === "reassurance",
    );

    expect(trustLines.length).toBeGreaterThan(0);
    for (const caveat of trustLines) {
      expect(plan.decision.proposal).not.toContain(caveat.text);
    }
    expect(plan.decision.proposal).not.toMatch(/Juli không tự/i);
  });

  it("ties the impact block and the situation deep link to the same Main KPI — GMV", () => {
    const plan = getPreventReturnPlanReview();

    expect(defaultPreventReturnAnalyticsMetricKey).toBe("gmv-tiktok");
    expect(plan.impact.metricKey).toBe("gmv-tiktok");
    expect(plan.situation.analyticsMetricHref).toBe("/analytics/gmv-tiktok");
  });

  it("carries a directional goal and never a projected magnitude", () => {
    const plan = getPreventReturnPlanReview();

    expect(plan.impact.directionalGoal).toMatch(/^Mục tiêu:/);
    expect(plan.impact.directionalGoal).not.toMatch(/\d/);
  });

  /**
   * `prevent_return_8b` carries the restock-gating warning in `risks`. Its
   * display is deliberately deferred (ADR-055 items 9 and 14): it is neither
   * rendered nor paraphrased back in as body copy.
   */
  it("does not carry the risks copy, nor the restock-gating wording, anywhere", () => {
    expect(fixture?.risks).toBeTruthy();
    for (const text of collectPlanStrings()) {
      expect(text).not.toContain(fixture!.risks);
      expect(text).not.toMatch(/không tự động nhập lại kho/i);
      expect(text).not.toMatch(/chỉ nhập lại kho/i);
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
    expect(getWorkflowPlanReview(PREVENT_RETURN_WORKFLOW_KEY)?.workflowKey).toBe(
      PREVENT_RETURN_WORKFLOW_KEY,
    );
  });
});
