import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../recommendations";
import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_REFUND_WORKFLOW_KEY,
  PREVENT_RETURN_FBT_INTAKE_KEY,
  PREVENT_RETURN_WORKFLOW_KEY,
  defaultAnalyticsMetricKey,
  getReviewStage,
  getWorkflowReviewStages,
  isReviewExecutableWorkflow,
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

  it("returns five-stage review flows for workflows 7–9 with no Approve/Reject default", () => {
    for (const workflowKey of [
      PREVENT_CANCELLATION_WORKFLOW_KEY,
      PREVENT_RETURN_WORKFLOW_KEY,
      PREVENT_REFUND_WORKFLOW_KEY,
    ]) {
      const stages = getWorkflowReviewStages(workflowKey);
      expect(stages.map((stage) => stage.stage)).toEqual([
        "why",
        "analytics",
        "inputs",
        "preview",
        "approve",
      ]);

      const inputs = getReviewStage(workflowKey, "inputs");
      const decision = inputs?.inputFields?.find(
        (field) => field.key === "seller_decision",
      );
      expect(decision?.prefillValue).toBe("");
      expect(decision?.editable).toBe(true);
      expect(decision?.required).toBe(true);
    }
  });

  it("returns no stages for unsupported workflow keys including FBT intake scaffold", () => {
    expect(getWorkflowReviewStages("optimize_product_2")).toEqual([]);
    expect(getWorkflowReviewStages(PREVENT_RETURN_FBT_INTAKE_KEY)).toEqual([]);
    expect(isReviewExecutableWorkflow(PREVENT_RETURN_FBT_INTAKE_KEY)).toBe(
      false,
    );
  });
});
