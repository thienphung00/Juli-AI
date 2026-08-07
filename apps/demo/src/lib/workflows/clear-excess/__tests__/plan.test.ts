import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import { getWorkflowPlanReview } from "../../../plan-reviews";
import {
  CLEAR_EXCESS_WORKFLOW_KEY,
  buildClearExcessReviewInputDefaults,
  defaultClearExcessAnalyticsMetricKey,
} from "../review";
import { getClearExcessPlanReview } from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === CLEAR_EXCESS_WORKFLOW_KEY,
);

function collectPlanStrings(): string[] {
  const plan = getClearExcessPlanReview();
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

describe("getClearExcessPlanReview", () => {
  it("returns the full Situation → Decision → Details spine", () => {
    const plan = getClearExcessPlanReview();

    expect(plan.workflowKey).toBe(CLEAR_EXCESS_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
    // Four seller decisions: the markdown and promotion type rest in Decision,
    // the promotion window is branch-gated execution detail (ADR-055 item 8).
    expect(plan.details?.detailLines.length).toBeGreaterThan(0);
  });

  it("states the proposal in exactly one sentence", () => {
    const plan = getClearExcessPlanReview();

    const sentences = plan.decision.proposal
      .split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);
    expect(sentences).toHaveLength(1);
  });

  it("collapses the three known fields into one summary row with a count", () => {
    const plan = getClearExcessPlanReview();

    expect(plan.situation.summary).toContain("3 thông tin");
    expect(plan.situation.detailLines).toHaveLength(3);
  });

  it("phrases the situation disclosure as a question", () => {
    const plan = getClearExcessPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
  });

  it("proposes the markdown and promotion type held in the field data", () => {
    const plan = getClearExcessPlanReview();
    const defaults = buildClearExcessReviewInputDefaults();

    expect(plan.decision.proposal).toContain(`${defaults.markdown_baseline}%`);
    expect(plan.decision.proposal.toLowerCase()).toContain(
      defaults.activity_type.toLowerCase(),
    );
  });

  it("carries the promotion window as branch-gated Details, from the field data", () => {
    const plan = getClearExcessPlanReview();
    const details = (plan.details?.detailLines ?? []).join(" ");

    expect(details).toContain("07/08/2026");
    expect(details).toContain("21/08/2026");
  });

  it("carries the workflow's reasoning behind the decision disclosure — never empty", () => {
    const plan = getClearExcessPlanReview();

    expect(plan.decision.reasoning).toBe(fixture?.reasoning);
    expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
  });

  it("ties the impact block and the situation deep link to the same Main KPI — AOV", () => {
    const plan = getClearExcessPlanReview();

    expect(defaultClearExcessAnalyticsMetricKey).toBe("aov");
    expect(plan.impact.metricKey).toBe("aov");
    expect(plan.situation.analyticsMetricHref).toBe("/analytics/aov");
  });

  it("carries a directional goal and never a projected magnitude", () => {
    const plan = getClearExcessPlanReview();

    expect(plan.impact.directionalGoal).toMatch(/^Mục tiêu:/);
    expect(plan.impact.directionalGoal).not.toMatch(/\d/);
    // The fixture's projected VND amount never reaches the card.
    for (const text of collectPlanStrings()) {
      expect(text).not.toContain(fixture!.expectedImpactLabel);
    }
  });

  /**
   * clear_excess_4 carries the irreversibility warning ("không thể hoàn tác").
   * Its display is deliberately deferred (ADR-055 items 9 and 14): `risks` is
   * not rendered, and it must not be smuggled back in as body copy.
   */
  it("does not carry the risks copy, nor the irreversibility wording, anywhere in the plan", () => {
    expect(fixture?.risks).toBeTruthy();
    for (const text of collectPlanStrings()) {
      expect(text).not.toContain(fixture!.risks);
      expect(text).not.toMatch(/không thể hoàn tác/i);
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
    expect(getWorkflowPlanReview(CLEAR_EXCESS_WORKFLOW_KEY)?.workflowKey).toBe(
      CLEAR_EXCESS_WORKFLOW_KEY,
    );
  });
});
