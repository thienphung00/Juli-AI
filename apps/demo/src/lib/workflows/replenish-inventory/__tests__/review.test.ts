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
  it("returns five stages with the GMV analytics deep-link by default", () => {
    const stages = getReplenishInventoryReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    // ADR-055 item 15 ties replenish_inventory_3 to GMV, not cancellation rate.
    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricKey).toBe("gmv-tiktok");
    expect(analytics?.analyticsMetricHref).toBe("/analytics/gmv-tiktok");
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

  it("prefills reorder quantity from computed inputs when available", () => {
    const computedQuantity = 96;
    const inputs = getReplenishInventoryReviewStages(
      "cancellation-rate",
      computedQuantity,
    ).find((stage) => stage.stage === "inputs");

    const reorderQtyField = inputs?.inputFields?.find(
      (f) => f.key === "reorder_quantity",
    );

    expect(reorderQtyField?.prefillValue).toBe("96");
    expect(reorderQtyField?.editable).toBe(true);
  });

  it("returns fallback message when computed quantity is unavailable", () => {
    const inputs = getReplenishInventoryReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    const reorderQtyField = inputs?.inputFields?.find(
      (f) => f.key === "reorder_quantity",
    );

    expect(reorderQtyField?.prefillValue).toMatch(/chưa có mặc định/i);
    expect(reorderQtyField?.editable).toBe(true);
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
  it("provides proposed reorder quantity and supplier path as seller-facing defaults", () => {
    const defaults = buildReplenishInventoryReviewInputDefaults();

    expect(defaults.reorder_quantity).not.toBe("");
    expect(defaults.external_path).not.toBe("");
    expect(defaults.warehouse_id).toMatch(/WH-HCM/);
  });

  it("populates reorder quantity from computed value when available", () => {
    const computedQuantity = 120.5;
    const defaults = buildReplenishInventoryReviewInputDefaults(computedQuantity);

    expect(defaults.reorder_quantity).toBe("121"); // ceil(120.5) = 121
    expect(defaults.warehouse_id).toMatch(/WH-HCM/);
  });

  it("remains editable even when prefilled with computed quantity", () => {
    const computedQuantity = 96;
    const defaults = buildReplenishInventoryReviewInputDefaults(computedQuantity);
    const stages = getReplenishInventoryReviewStages(
      "cancellation-rate",
      computedQuantity,
    );

    const inputsStage = stages.find((s) => s.stage === "inputs");
    const reorderQtyField = inputsStage?.inputFields?.find(
      (f) => f.key === "reorder_quantity",
    );

    expect(reorderQtyField?.editable).toBe(true);
    expect(defaults.reorder_quantity).toBe("96");
  });
});
