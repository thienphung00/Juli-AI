import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import {
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
    expect(why?.body).toContain(fixture!.risks);
    expect(why?.body).not.toMatch(/\bFBS\b/);
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

  it("uses seller-language preview with fulfillment summary and no backend jargon", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === PROCESS_ORDER_WORKFLOW_KEY,
    );
    const preview = getProcessOrderReviewStages().find(
      (stage) => stage.stage === "preview",
    );

    expect(preview?.body).toContain(fixture!.sellerReason);
    expect(preview?.body).toMatch(/Ngưỡng thời gian.*chưa được xác định/i);
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(preview?.body ?? "").not.toMatch(pattern);
    }
  });
});
