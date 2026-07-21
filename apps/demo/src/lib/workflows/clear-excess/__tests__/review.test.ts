import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import {
  CLEAR_EXCESS_WORKFLOW_KEY,
  buildClearExcessReviewInputDefaults,
  getClearExcessReviewStages,
} from "../review";

const clearExcessFixture = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === CLEAR_EXCESS_WORKFLOW_KEY,
);

describe("getClearExcessReviewStages", () => {
  it("returns five stages with stock-health analytics deep-link by default", () => {
    const stages = getClearExcessReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricKey).toBe("stock-health");
    expect(analytics?.analyticsMetricHref).toBe("/analytics/stock-health");
  });

  it("derives Why-stage copy from the clear_excess recommendation fixture", () => {
    expect(clearExcessFixture).toBeDefined();

    const why = getClearExcessReviewStages().find((stage) => stage.stage === "why");

    expect(why?.body).toContain(clearExcessFixture!.reasoning);
    expect(why?.body).toContain(clearExcessFixture!.signal);
    expect(why?.body).toContain(clearExcessFixture!.evidence);
    expect(why?.body).toContain(clearExcessFixture!.risks);
  });

  it("labels Flash Sale eligibility as unresolved and zero-floor stock as a later irreversible step", () => {
    const inputs = getClearExcessReviewStages().find((stage) => stage.stage === "inputs");
    const preview = getClearExcessReviewStages().find((stage) => stage.stage === "preview");

    const flashSaleField = inputs?.inputFields?.find(
      (field) => field.key === "flash_sale_eligibility",
    );
    const zeroStockField = inputs?.inputFields?.find(
      (field) => field.key === "zero_floor_stock_ack",
    );

    expect(flashSaleField?.prefillValue).toMatch(/chưa kiểm tra|chờ xác minh/i);
    expect(flashSaleField?.prefillValue).not.toMatch(/đủ điều kiện|eligible/i);
    expect(flashSaleField?.editable).toBe(false);

    expect(inputs?.body).toMatch(/không thể hoàn tác|bước sau/i);
    expect(zeroStockField?.required).toBe(false);
    expect(zeroStockField?.editable).toBe(false);
    expect(zeroStockField?.prefillValue).toMatch(/bước sau|chưa phê duyệt/i);

    expect(preview?.body).toContain(clearExcessFixture!.knownLimits);
    expect(preview?.body).toMatch(/FBT.*chưa|Unresolved|Chưa được hỗ trợ/i);
  });

  it("does not invent markdown defaults or resolved sell-through thresholds", () => {
    const defaults = buildClearExcessReviewInputDefaults();
    const inputs = getClearExcessReviewStages().find((stage) => stage.stage === "inputs");

    expect(defaults.markdown_baseline).toBe("");
    expect(defaults.activity_type).toBe("");
    expect(defaults.promotion_start_date).toBe("");
    expect(defaults.promotion_end_date).toBe("");

    const markdownField = inputs?.inputFields?.find(
      (field) => field.key === "markdown_baseline",
    );
    expect(markdownField?.prefillValue).toBe("");

    expect(inputs?.body).toMatch(/ngưỡng.*chưa được xác định|chưa được xác định/i);
    expect(clearExcessFixture!.knownLimits).toMatch(/chưa được xác định/i);
  });

  it("requires explicit promotion window dates without prefilled values", () => {
    const inputs = getClearExcessReviewStages().find((stage) => stage.stage === "inputs");

    expect(inputs?.inputFields).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "promotion_start_date",
          prefillValue: "",
          required: true,
          editable: true,
        }),
        expect.objectContaining({
          key: "promotion_end_date",
          prefillValue: "",
          required: true,
          editable: true,
        }),
      ]),
    );
  });
});
