import { describe, expect, it } from "vitest";

import {
  getPlanCaveats,
  getReassuranceCaveats,
} from "../../../plan-caveats";
import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import { getWorkflowPlanReview } from "../../../plan-reviews";
import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  getCreateHeroProductReviewStages,
} from "../review";
import { getCreateHeroProductPlanReview } from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === CREATE_HERO_PRODUCT_WORKFLOW_KEY,
);

function collectPlanStrings(): string[] {
  const plan = getCreateHeroProductPlanReview();
  return [
    plan.title,
    plan.decision.proposal,
    plan.decision.reasoning,
    plan.situation.summary,
    plan.situation.disclosureQuestion,
    ...plan.situation.detailLines,
    ...plan.decision.caveats.map((caveat) => caveat.text),
    plan.needsYou!.title,
    plan.needsYou!.explanation,
    plan.needsYou!.approvalBlockedText,
    ...plan.needsYou!.uploadFields.map((field) => field.label),
  ];
}

describe("getCreateHeroProductPlanReview", () => {
  it("returns the Situation → Decision spine with no Details section", () => {
    const plan = getCreateHeroProductPlanReview();

    expect(plan.workflowKey).toBe(CREATE_HERO_PRODUCT_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
    // Details is absent — no branch discriminator, not an empty stub.
    expect(plan.details).toBeUndefined();
  });

  it("states the proposal in exactly one sentence", () => {
    const plan = getCreateHeroProductPlanReview();

    const sentences = plan.decision.proposal
      .split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);
    expect(sentences).toHaveLength(1);
  });

  it("collapses the known fields into a count matching the detail lines", () => {
    const plan = getCreateHeroProductPlanReview();

    expect(plan.situation.summary).toContain(
      `${plan.situation.detailLines.length} thông tin`,
    );
  });

  it("phrases the situation disclosure as a question", () => {
    const plan = getCreateHeroProductPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
  });

  it("carries the workflow's reasoning behind the decision disclosure — never empty", () => {
    const plan = getCreateHeroProductPlanReview();

    expect(plan.decision.reasoning).toBe(fixture?.reasoning);
    expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
  });

  it("carries typed caveats — both hidden classes, and no invented trust line", () => {
    const plan = getCreateHeroProductPlanReview();

    expect(plan.decision.caveats).toEqual(
      getPlanCaveats(CREATE_HERO_PRODUCT_WORKFLOW_KEY),
    );
    expect(
      plan.decision.caveats.map((caveat) => caveat.caveatClass),
    ).toEqual(["threshold-undefined", "fulfilment-unsupported"]);
    // ADR-055 item 19 excludes this workflow from repeat consent through the
    // upload exception itself, not through authored class-D copy — so there
    // is no reassurance caveat, and none is invented to fill the gap.
    expect(
      getReassuranceCaveats(CREATE_HERO_PRODUCT_WORKFLOW_KEY),
    ).toHaveLength(0);
  });

  it("ties the impact block to the workflow's existing GMV binding", () => {
    const plan = getCreateHeroProductPlanReview();

    expect(plan.impact.metricKey).toBe("gmv-tiktok");
    expect(plan.situation.analyticsMetricHref).toBe("/analytics/gmv-tiktok");
  });

  describe("needs-you section (ADR-055 item 12)", () => {
    it("carries both upload descriptors, sourced from the canonical field data", () => {
      const plan = getCreateHeroProductPlanReview();
      const inputsStage = getCreateHeroProductReviewStages().find(
        (stage) => stage.stage === "inputs",
      );
      const uploadDescriptors = (inputsStage?.inputFields ?? []).filter(
        (field) => field.kind === "upload",
      );

      expect(plan.needsYou?.uploadFields).toEqual(
        uploadDescriptors.map((field) => ({
          key: field.key,
          label: field.label,
          required: field.required,
        })),
      );
    });

    it("keeps the authored labels verbatim — required images, optional supporting file", () => {
      const plan = getCreateHeroProductPlanReview();

      expect(plan.needsYou?.uploadFields).toEqual([
        { key: "main_images", label: "Ảnh sản phẩm", required: true },
        {
          key: "supporting_file",
          label: "Tệp hỗ trợ (nếu danh mục yêu cầu)",
          required: false,
        },
      ]);
    });

    it("explains itself instead of resting as a bare empty form", () => {
      const plan = getCreateHeroProductPlanReview();

      expect(plan.needsYou?.explanation.trim().length).toBeGreaterThan(0);
      expect(plan.needsYou?.approvalBlockedText.trim().length).toBeGreaterThan(
        0,
      );
      // Why Juli cannot propose here: it does not invent the shop's photos.
      expect(plan.needsYou?.explanation).toContain("không tự tạo");
    });

    it("proposes no imagery — the upload field data carries no prefill", () => {
      const inputsStage = getCreateHeroProductReviewStages().find(
        (stage) => stage.stage === "inputs",
      );
      for (const field of (inputsStage?.inputFields ?? []).filter(
        (candidate) => candidate.kind === "upload",
      )) {
        expect(field.prefillValue).toBe("");
      }
    });
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

  it("keeps every plan string free of system vocabulary and security-gate claims", () => {
    for (const text of collectPlanStrings()) {
      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(text).not.toMatch(pattern);
      }
    }
  });
});

describe("getWorkflowPlanReview routing", () => {
  it("returns the plan for create_hero_product_1 — the upload exception is on the spine", () => {
    const plan = getWorkflowPlanReview(CREATE_HERO_PRODUCT_WORKFLOW_KEY);

    expect(plan).not.toBeNull();
    expect(plan?.needsYou?.uploadFields).toHaveLength(2);
  });
});
