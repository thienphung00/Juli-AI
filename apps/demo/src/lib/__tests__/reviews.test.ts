import { describe, expect, it } from "vitest";

import { MAIN_KPI_ORDER } from "../analytics/main-kpis";
import { recommendationFixtures } from "../recommendations";
import {
  APPROVABLE_WORKFLOW_KEYS,
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
import { getOptimizeProductReviewStages } from "../workflows/optimize-product/review";
import { getReplenishInventoryReviewStages } from "../workflows/replenish-inventory/review";
import { getClearExcessReviewStages } from "../workflows/clear-excess/review";
import { getProcessOrderReviewStages } from "../workflows/process-order/review";
import { getCreateActivityReviewStages } from "../workflows/create-activity/review";
import { getUpdateActivityReviewStages } from "../workflows/update-activity/review";
import { getDeleteActivityReviewStages } from "../workflows/delete-activity/review";
import { getPreventCancellationReviewStages } from "../workflows/prevent-cancellation/review";
import { getPreventReturnReviewStages } from "../workflows/prevent-return/review";
import { getPreventRefundReviewStages } from "../workflows/prevent-refund/review";

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

  it("returns five stages for workflow 5 process_order", () => {
    const stages = getWorkflowReviewStages("process_order_5");

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);
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
    expect(getWorkflowReviewStages("not_a_real_workflow_key")).toEqual([]);
    expect(getWorkflowReviewStages(PREVENT_RETURN_FBT_INTAKE_KEY)).toEqual([]);
    expect(isReviewExecutableWorkflow(PREVENT_RETURN_FBT_INTAKE_KEY)).toBe(
      false,
    );
  });
});

describe("Analytics metric key validation across all workflows", () => {
  it("ensures every approvable workflow's default analyticsMetricKey is valid in the Demo catalog", () => {
    const workflowFunctionMap = {
      optimize_product_2: getOptimizeProductReviewStages,
      replenish_inventory_3: getReplenishInventoryReviewStages,
      clear_excess_4: getClearExcessReviewStages,
      process_order_5: getProcessOrderReviewStages,
      create_activity_7a: getCreateActivityReviewStages,
      update_activity_7c: getUpdateActivityReviewStages,
      delete_activity_7b: getDeleteActivityReviewStages,
      prevent_cancellation_8a: getPreventCancellationReviewStages,
      prevent_return_8b: getPreventReturnReviewStages,
      prevent_refund_8c: getPreventRefundReviewStages,
      create_hero_product_1: () => getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY),
    };

    for (const workflowKey of APPROVABLE_WORKFLOW_KEYS) {
      const stageFn = workflowFunctionMap[workflowKey as keyof typeof workflowFunctionMap];
      expect(stageFn, `${workflowKey} must have a workflow function`).toBeDefined();

      const stages = stageFn();
      const analyticsStage = stages.find((stage) => stage.stage === "analytics");

      expect(
        analyticsStage?.analyticsMetricKey,
        `${workflowKey} must have an analyticsMetricKey`,
      ).toBeDefined();

      const metricKey = analyticsStage?.analyticsMetricKey;
      expect(
        MAIN_KPI_ORDER.includes(metricKey as any),
        `${workflowKey} analytics metric key "${metricKey}" must be in MAIN_KPI_ORDER: ${MAIN_KPI_ORDER.join(", ")}`,
      ).toBe(true);
    }
  });

  it("ensures every analytics stage has an href matching the analyticsMetricKey", () => {
    const workflowFunctionMap = {
      optimize_product_2: getOptimizeProductReviewStages,
      replenish_inventory_3: getReplenishInventoryReviewStages,
      clear_excess_4: getClearExcessReviewStages,
      process_order_5: getProcessOrderReviewStages,
      create_activity_7a: getCreateActivityReviewStages,
      update_activity_7c: getUpdateActivityReviewStages,
      delete_activity_7b: getDeleteActivityReviewStages,
      prevent_cancellation_8a: getPreventCancellationReviewStages,
      prevent_return_8b: getPreventReturnReviewStages,
      prevent_refund_8c: getPreventRefundReviewStages,
      create_hero_product_1: () => getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY),
    };

    for (const workflowKey of APPROVABLE_WORKFLOW_KEYS) {
      const stageFn = workflowFunctionMap[workflowKey as keyof typeof workflowFunctionMap];
      const stages = stageFn();
      const analyticsStage = stages.find((stage) => stage.stage === "analytics");

      expect(
        analyticsStage?.analyticsMetricHref,
        `${workflowKey} must have an analyticsMetricHref`,
      ).toBeDefined();

      expect(analyticsStage?.analyticsMetricHref).toBe(
        `/analytics/${analyticsStage?.analyticsMetricKey}`,
      );
    }
  });
});
