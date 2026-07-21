import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import {
  REPLENISH_INVENTORY_TOOL_NAME,
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
    expect(why?.body).toContain(replenishFixture!.evidence);
    expect(why?.body).toContain(replenishFixture!.signal);
  });

  it("labels Supplier/ERP path and reorder quantity as unresolved in Inputs", () => {
    const inputs = getReplenishInventoryReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    expect(inputs?.body).toMatch(/Unresolved/i);
    expect(inputs?.body).toMatch(/NCC|ERP/i);

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
          prefillValue: expect.stringMatching(/Unresolved/i),
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

    expect(preview?.body).toContain(REPLENISH_INVENTORY_TOOL_NAME);
    expect(preview?.body).toMatch(/Unresolved/i);
    expect(preview?.body).toContain("replenish_inventory_3b");
    expect(preview?.body).not.toMatch(/hợp đồng NCC đã kết nối|ERP đã kết nối/i);

    expect(approve?.body).toMatch(/Unresolved/i);
    expect(approve?.body).toMatch(/Purchase Order|đơn mua/i);
    expect(approve?.body).not.toMatch(/API NCC|API ERP/i);
  });
});

describe("buildReplenishInventoryReviewInputDefaults", () => {
  it("keeps reorder quantity empty when ROP/EOQ default is unavailable", () => {
    const defaults = buildReplenishInventoryReviewInputDefaults();

    expect(defaults.reorder_quantity).toBe("");
    expect(defaults.warehouse_id).toMatch(/WH-FBS/);
  });
});
