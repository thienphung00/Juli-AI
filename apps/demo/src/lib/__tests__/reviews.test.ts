import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../recommendations";
import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  defaultAnalyticsMetricKey,
  getReviewStage,
  getWorkflowReviewStages,
} from "../reviews";

describe("getWorkflowReviewStages", () => {
  it("returns five stages for workflow 1 with analytics deep-link", () => {
    const stages = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY);

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = getReviewStage(
      CREATE_HERO_PRODUCT_WORKFLOW_KEY,
      "analytics",
    );
    expect(analytics?.analyticsMetricHref).toBe(
      `/analytics/${defaultAnalyticsMetricKey}`,
    );
  });

  it("derives Why-stage copy from the recommendation fixture without duplicating fixture data inline", () => {
    const fixture = recommendationFixtures[0];
    const why = getReviewStage(CREATE_HERO_PRODUCT_WORKFLOW_KEY, "why");

    expect(why?.body).toContain(fixture.reasoning);
    expect(why?.body).toContain(fixture.evidence);
  });

  it("describes editable Inputs fields with catalog prefill rules", () => {
    const inputs = getReviewStage(CREATE_HERO_PRODUCT_WORKFLOW_KEY, "inputs");

    expect(inputs?.inputFields).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "category_id",
          editable: false,
          required: true,
        }),
        expect.objectContaining({
          key: "main_images",
          prefillValue: "",
          required: true,
          editable: true,
        }),
        expect.objectContaining({
          key: "warehouse_id",
          editable: false,
          required: true,
        }),
      ]),
    );
  });

  it("returns five stages for workflow 2 optimize_product", () => {
    const stages = getWorkflowReviewStages("optimize_product_2");

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);
  });

  it("returns no stages for unsupported workflow keys", () => {
    expect(getWorkflowReviewStages("process_order_5")).toEqual([]);
  });
});
