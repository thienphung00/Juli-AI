import { describe, expect, it } from "vitest";

import { PLAN_REASONING_DISCLOSURE_QUESTION } from "../plan-reviews";
import { recommendationFixtures } from "../recommendations";
import {
  REVIEW_UI_BANNED_PATTERNS,
  sanitizeSellerReviewText,
} from "../review-seller-copy";

/**
 * Reasoning disclosure content (ADR-055 items 3, 11).
 *
 * The expansion is a reasoning container, not a limits container: `reasoning`
 * is pre-authored for all eleven workflows in the shared fixture table, so the
 * question-labelled ask affordance is never empty — on any workflow.
 */
describe("reasoning disclosure content", () => {
  it("labels the disclosure as a question, not a noun", () => {
    expect(PLAN_REASONING_DISCLOSURE_QUESTION).toContain(
      "Vì sao Juli đề xuất điều này",
    );
    expect(PLAN_REASONING_DISCLOSURE_QUESTION.trim().endsWith("?")).toBe(true);
  });

  it("is never empty on any of the eleven workflows in the shared table", () => {
    expect(recommendationFixtures).toHaveLength(11);

    for (const fixture of recommendationFixtures) {
      const revealed = sanitizeSellerReviewText(fixture.reasoning);
      expect(revealed.trim().length).toBeGreaterThan(0);
    }
  });

  it("stays one short seller sentence after sanitizing — no multi-paragraph dump", () => {
    for (const fixture of recommendationFixtures) {
      const revealed = sanitizeSellerReviewText(fixture.reasoning);
      expect(revealed).not.toContain("\n");
    }
  });

  it("keeps the disclosure label free of system vocabulary", () => {
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(PLAN_REASONING_DISCLOSURE_QUESTION).not.toMatch(pattern);
    }
  });
});
