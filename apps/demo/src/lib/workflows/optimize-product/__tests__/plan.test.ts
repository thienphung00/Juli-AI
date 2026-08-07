import { describe, expect, it } from "vitest";

import {
  getPlanCaveats,
  getReasoningCaveats,
  getReassuranceCaveats,
} from "../../../plan-caveats";
import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import { getWorkflowPlanReview } from "../../../plan-reviews";
import {
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  getOptimizeProductReviewStages,
} from "../review";
import { getOptimizeProductPlanReview } from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === OPTIMIZE_PRODUCT_WORKFLOW_KEY,
);

function collectPlanStrings(): string[] {
  const plan = getOptimizeProductPlanReview();
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
    ...optionStrings,
    ...plan.decision.caveats.map((caveat) => caveat.text),
  ];
}

describe("getOptimizeProductPlanReview", () => {
  it("carries only the hidden undefined-threshold caveat — nothing reaches the seller", () => {
    const plan = getOptimizeProductPlanReview();

    expect(plan.decision.caveats).toEqual(
      getPlanCaveats(OPTIMIZE_PRODUCT_WORKFLOW_KEY),
    );
    expect(
      plan.decision.caveats.map((caveat) => caveat.caveatClass),
    ).toEqual(["threshold-undefined"]);
    expect(getReasoningCaveats(OPTIMIZE_PRODUCT_WORKFLOW_KEY)).toHaveLength(0);
    expect(getReassuranceCaveats(OPTIMIZE_PRODUCT_WORKFLOW_KEY)).toHaveLength(
      0,
    );
  });

  it("returns the Situation → Decision spine with no Details section", () => {
    const plan = getOptimizeProductPlanReview();

    expect(plan.workflowKey).toBe(OPTIMIZE_PRODUCT_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
    // No branch discriminator, so Details is absent — not an empty stub.
    expect(plan.details).toBeUndefined();
  });

  it("states the proposal in exactly one sentence", () => {
    const plan = getOptimizeProductPlanReview();

    const sentences = plan.decision.proposal
      .split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);
    expect(sentences).toHaveLength(1);
  });

  it("collapses the three known fields into one summary row with a count", () => {
    const plan = getOptimizeProductPlanReview();

    expect(plan.situation.summary).toContain("3 thông tin");
    expect(plan.situation.detailLines).toHaveLength(3);
  });

  it("phrases both disclosures as questions", () => {
    const plan = getOptimizeProductPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
    expect(
      plan.decision.recommendedOptions?.disclosureQuestion.trim().endsWith("?"),
    ).toBe(true);
  });

  it("carries the two seller decisions as recommended option groups", () => {
    const plan = getOptimizeProductPlanReview();

    const groups = plan.decision.recommendedOptions?.groups;
    expect(groups).toHaveLength(2);
    expect(groups?.map((group) => group.label)).toEqual([
      "Tiêu đề SEO",
      "Mô tả SEO",
    ]);
  });

  it("renders the recommended options from the field descriptors, with the proposed value marked", () => {
    const plan = getOptimizeProductPlanReview();
    const inputsStage = getOptimizeProductReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    for (const [index, fieldKey] of ["seo_title", "seo_description"].entries()) {
      const field = inputsStage?.inputFields?.find(
        (candidate) => candidate.key === fieldKey,
      );
      const group = plan.decision.recommendedOptions?.groups[index];

      expect(group?.options.map((option) => option.value)).toEqual(
        field?.options?.map((option) => option.value),
      );

      const proposed = group?.options.filter((option) => option.proposed);
      expect(proposed).toHaveLength(1);
      expect(proposed?.[0]?.value).toBe(field?.prefillValue);
    }
  });

  it("carries the workflow's reasoning behind the decision disclosure — never empty", () => {
    const plan = getOptimizeProductPlanReview();

    expect(plan.decision.reasoning).toBe(fixture?.reasoning);
    expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
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
    const plan = getOptimizeProductPlanReview();

    expect(plan.situation.analyticsMetricHref).toBe("/analytics/ctor");
  });

  it("is served by the plan review registry", () => {
    expect(getWorkflowPlanReview(OPTIMIZE_PRODUCT_WORKFLOW_KEY)?.workflowKey).toBe(
      OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    );
  });
});
