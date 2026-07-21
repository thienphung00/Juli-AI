import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import {
  PROCESS_ORDER_FBT_INTAKE_KEY,
  PROCESS_ORDER_WORKFLOW_KEY,
  defaultProcessOrderAnalyticsMetricKey,
  getProcessOrderReviewStages,
} from "../review";

describe("getProcessOrderReviewStages", () => {
  it("returns five stages for workflow 5 with analytics deep-link", () => {
    const stages = getProcessOrderReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricHref).toBe(
      `/analytics/${defaultProcessOrderAnalyticsMetricKey}`,
    );
  });

  it("honours a custom analyticsMetricKey in the analytics href", () => {
    const analytics = getProcessOrderReviewStages(
      "orders-awaiting-shipment",
    ).find((stage) => stage.stage === "analytics");

    expect(analytics?.analyticsMetricHref).toBe(
      "/analytics/orders-awaiting-shipment",
    );
  });

  it("derives Why-stage copy from the process_order_5 recommendation fixture", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === PROCESS_ORDER_WORKFLOW_KEY,
    );
    expect(fixture).toBeDefined();

    const why = getProcessOrderReviewStages().find(
      (stage) => stage.stage === "why",
    );

    expect(why?.body).toContain(fixture!.reasoning);
    expect(why?.body).toContain(fixture!.signal);
    expect(why?.body).toContain(fixture!.evidence);
    expect(why?.body).toContain(fixture!.risks);
  });

  it("describes read-only T5 priority and off-by-default split/combine inputs", () => {
    const inputs = getProcessOrderReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    expect(inputs?.inputFields).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "order_priority",
          editable: false,
          required: true,
        }),
        expect.objectContaining({
          key: "shipping_type",
          required: true,
          editable: true,
        }),
        expect.objectContaining({
          key: "split_combine",
          required: false,
          editable: true,
        }),
        expect.objectContaining({
          key: "tracking_number",
          prefillValue: "",
          required: false,
          editable: true,
        }),
        expect.objectContaining({
          key: "shipping_provider_id",
          prefillValue: "",
          required: false,
          editable: true,
        }),
      ]),
    );
  });

  it("labels FBT scaffold as unfilled and cites unresolved SLA trigger without inventing thresholds", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === PROCESS_ORDER_WORKFLOW_KEY,
    );
    const preview = getProcessOrderReviewStages().find(
      (stage) => stage.stage === "preview",
    );

    expect(preview?.body).toContain(fixture!.toolName);
    expect(preview?.body).toContain(fixture!.capabilityLabel);
    expect(preview?.body).toContain(fixture!.knownLimits);
    expect(preview?.body).toContain(PROCESS_ORDER_FBT_INTAKE_KEY);
    expect(preview?.body).toMatch(/Unresolved|Unfilled|chưa/i);
    expect(fixture!.knownLimits).toMatch(/Ngưỡng.*chưa được xác định/i);
  });
});
