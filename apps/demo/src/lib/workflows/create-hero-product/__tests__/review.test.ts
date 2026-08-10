import { describe, expect, it } from "vitest";

import {
  buildReviewInputDefaults,
  getWorkflowReviewStages,
} from "../../../reviews";
import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  buildCreateHeroProductReviewInputDefaults,
  getCreateHeroProductReviewStages,
} from "../review";

describe("getCreateHeroProductReviewStages", () => {
  it("returns the five stages in order", () => {
    const stages = getCreateHeroProductReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);
  });

  it("is what the shared reviews registry delegates to", () => {
    // reviews.ts no longer builds these stages inline (ADR-055
    // Consequences): the registry answer and the module answer are the same.
    expect(getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY)).toEqual(
      getCreateHeroProductReviewStages(),
    );
    expect(buildReviewInputDefaults()).toEqual(
      buildCreateHeroProductReviewInputDefaults(),
    );
  });

  it("carries the two upload descriptors with authored labels and no prefill", () => {
    const inputsStage = getCreateHeroProductReviewStages().find(
      (stage) => stage.stage === "inputs",
    );
    const uploadFields = (inputsStage?.inputFields ?? []).filter(
      (field) => field.kind === "upload",
    );

    expect(
      uploadFields.map((field) => ({
        key: field.key,
        label: field.label,
        required: field.required,
        prefillValue: field.prefillValue,
      })),
    ).toEqual([
      {
        key: "main_images",
        label: "Ảnh sản phẩm",
        required: true,
        prefillValue: "",
      },
      {
        key: "supporting_file",
        label: "Tệp hỗ trợ (nếu danh mục yêu cầu)",
        required: false,
        prefillValue: "",
      },
    ]);
  });

  it("resolves the analytics link from the tied GMV metric by default", () => {
    const analytics = getCreateHeroProductReviewStages().find(
      (stage) => stage.stage === "analytics",
    );

    expect(analytics?.analyticsMetricHref).toBe("/analytics/gmv-tiktok");
  });
});
