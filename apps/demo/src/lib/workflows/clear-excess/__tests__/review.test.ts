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
  it("returns five stages with aov analytics deep-link by default", () => {
    const stages = getClearExcessReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricKey).toBe("aov");
    expect(analytics?.analyticsMetricHref).toBe("/analytics/aov");
  });

  it("derives Why-stage copy from the clear_excess recommendation fixture", () => {
    expect(clearExcessFixture).toBeDefined();

    const why = getClearExcessReviewStages().find((stage) => stage.stage === "why");

    expect(why?.body).toContain(clearExcessFixture!.reasoning);
    expect(why?.body).toContain(clearExcessFixture!.signal);
    expect(why?.body).toContain(clearExcessFixture!.risks);
    expect(why?.body).not.toMatch(/\bFBS\b/);
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

    expect(preview?.body).toContain(clearExcessFixture!.sellerReason);
    expect(preview?.body).toMatch(/giao hàng do TikTok quản lý.*chưa có trong Demo/i);
  });

  it("provides proposed markdown baseline and promotion window as seller-facing defaults", () => {
    const defaults = buildClearExcessReviewInputDefaults();
    const inputs = getClearExcessReviewStages().find((stage) => stage.stage === "inputs");

    expect(defaults.markdown_baseline).not.toBe("");
    expect(defaults.activity_type).not.toBe("");
    expect(defaults.promotion_start_date).not.toBe("");
    expect(defaults.promotion_end_date).not.toBe("");

    const markdownField = inputs?.inputFields?.find(
      (field) => field.key === "markdown_baseline",
    );
    expect(markdownField?.prefillValue).not.toBe("");

    expect(inputs?.body).toMatch(/ngưỡng.*chưa được xác định|chưa được xác định/i);
  });
});
