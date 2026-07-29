import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import {
  REPLENISH_INVENTORY_WORKFLOW_KEY,
  buildReplenishInventoryReviewInputDefaults,
  getReplenishInventoryReviewStages,
} from "../review";

const replenishFixture = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === REPLENISH_INVENTORY_WORKFLOW_KEY,
);

describe("getReplenishInventoryReviewStages", () => {
  it("returns five stages with stockout-rate analytics deep-link by default", () => {
    const stages = getReplenishInventoryReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricKey).toBe("stockout-rate");
    expect(analytics?.analyticsMetricHref).toBe("/analytics/stockout-rate");
  });

  it("derives Why-stage copy from the replenish_inventory_3 recommendation fixture", () => {
    expect(replenishFixture).toBeDefined();

    const why = getReplenishInventoryReviewStages().find(
      (stage) => stage.stage === "why",
    );

    expect(why?.body).toContain(replenishFixture!.reasoning);
    expect(why?.body).toContain("kho giao hàng");
    expect(why?.body).toContain(replenishFixture!.signal);
    expect(why?.body).not.toMatch(/\bFBS\b/);
  });

  it("labels Supplier/ERP path and reorder quantity as needing shop input in Inputs", () => {
    const inputs = getReplenishInventoryReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    expect(inputs?.body).toMatch(/NCC|ERP/i);
    expect(inputs?.body).not.toMatch(/Unresolved/i);

    expect(inputs?.inputFields).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "reorder_quantity",
          prefillValue: expect.stringMatching(/chưa có mặc định/i),
          editable: true,
          required: true,
        }),
        expect.objectContaining({
          key: "warehouse_id",
          editable: false,
          required: true,
        }),
        expect.objectContaining({
          key: "external_path",
          prefillValue: expect.stringMatching(/Chưa cấu hình/i),
        }),
      ]),
    );
  });

  it("does not fabricate a supplier or ERP integration contract in preview or approve", () => {
    const preview = getReplenishInventoryReviewStages().find(
      (stage) => stage.stage === "preview",
    );
    const approve = getReplenishInventoryReviewStages().find(
      (stage) => stage.stage === "approve",
    );

    expect(preview?.body).toContain(replenishFixture!.sellerReason);
    expect(preview?.body).not.toMatch(/hợp đồng NCC đã kết nối|ERP đã kết nối/i);
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(preview?.body ?? "").not.toMatch(pattern);
      expect(approve?.body ?? "").not.toMatch(pattern);
    }
  });
});

describe("buildReplenishInventoryReviewInputDefaults", () => {
  it("keeps reorder quantity empty when ROP/EOQ default is unavailable", () => {
    const defaults = buildReplenishInventoryReviewInputDefaults();

    expect(defaults.reorder_quantity).toBe("");
    expect(defaults.warehouse_id).toMatch(/WH-HCM/);
  });
});
