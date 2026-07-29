import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import {
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  defaultOptimizeProductAnalyticsMetricKey,
  getOptimizeProductReviewStages,
} from "../review";

describe("getOptimizeProductReviewStages", () => {
  it("returns five stages for workflow 2 with analytics deep-link", () => {
    const stages = getOptimizeProductReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricHref).toBe(
      `/analytics/${defaultOptimizeProductAnalyticsMetricKey}`,
    );
  });

  it("honours a custom analyticsMetricKey in the analytics href", () => {
    const analytics = getOptimizeProductReviewStages(
      "conversion-rate-by-category",
    ).find((stage) => stage.stage === "analytics");

    expect(analytics?.analyticsMetricHref).toBe(
      "/analytics/conversion-rate-by-category",
    );
  });

  it("derives Why-stage copy from the optimize_product_2 recommendation fixture", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    );
    expect(fixture).toBeDefined();

    const why = getOptimizeProductReviewStages().find(
      (stage) => stage.stage === "why",
    );

    expect(why?.body).toContain(fixture!.reasoning);
    expect(why?.body).toContain(fixture!.signal);
    expect(why?.body).toContain(fixture!.risks);
    expect(why?.body).not.toMatch(/\bFBS\b/);
  });

  it("describes editable Inputs fields with product prefill and off-by-default assets", () => {
    const inputs = getOptimizeProductReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    expect(inputs?.inputFields).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "product_id",
          editable: false,
          required: true,
        }),
        expect.objectContaining({
          key: "main_images",
          prefillValue: "",
          required: false,
          editable: true,
        }),
        expect.objectContaining({
          key: "supporting_file",
          prefillValue: "",
          required: false,
          editable: true,
        }),
        expect.objectContaining({
          key: "seo_title",
          required: true,
          editable: true,
        }),
        expect.objectContaining({
          key: "seo_description",
          required: true,
          editable: true,
        }),
        expect.objectContaining({
          key: "price",
          required: true,
          editable: true,
        }),
      ]),
    );
  });

  it("uses seller-language preview with margin-floor guard and no backend jargon", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    );
    const preview = getOptimizeProductReviewStages().find(
      (stage) => stage.stage === "preview",
    );

    expect(preview?.body).toContain(fixture!.sellerReason);
    expect(preview?.body).toMatch(/sàn lợi nhuận/i);
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(preview?.body ?? "").not.toMatch(pattern);
    }
  });
});
