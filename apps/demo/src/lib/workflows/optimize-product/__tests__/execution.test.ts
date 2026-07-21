import { beforeEach, describe, expect, it } from "vitest";

import {
  OPTIMIZE_PRODUCT_TOOL_NAME,
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  buildOptimizeProductExecution,
  createOptimizeProductTimeline,
  resetOptimizeProductExecutionCountersForTests,
} from "../execution";
import { buildOptimizeProductReviewInputDefaults } from "../review";

describe("createOptimizeProductTimeline", () => {
  it("maps Workflow 2 action, wait, and outcome screen-states to 11 FBS steps", () => {
    const timeline = createOptimizeProductTimeline();

    expect(timeline).toHaveLength(11);
    expect(timeline.map((step) => step.stepNumber)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
    ]);
    expect(timeline.every((step) => step.title.length > 0)).toBe(true);
  });

  it("includes a wait step for Product status change webhook #5 before the terminal outcome", () => {
    const timeline = createOptimizeProductTimeline();
    const waitStep = timeline.find((step) => step.kind === "wait");

    expect(waitStep?.stepNumber).toBe(10);
    expect(waitStep?.id).toBe("product-review-wait");
    expect(waitStep?.description).toMatch(/#5/);
  });

  it("ends with a live-outcome terminal outcome step", () => {
    const timeline = createOptimizeProductTimeline();
    const terminal = timeline[timeline.length - 1];

    expect(terminal.id).toBe("live-outcome");
    expect(terminal.kind).toBe("outcome");
    expect(terminal.stepNumber).toBe(11);
  });

  it("notes conditional skip branches for image, file, and price steps", () => {
    const timeline = createOptimizeProductTimeline();

    expect(
      timeline.find((step) => step.id === "upload-product-image")?.description,
    ).toMatch(/bỏ qua|chỉ/i);
    expect(
      timeline.find((step) => step.id === "upload-product-file")?.description,
    ).toMatch(/bỏ qua|chỉ/i);
    expect(
      timeline.find((step) => step.id === "update-price")?.description,
    ).toMatch(/bỏ qua|không đổi|chỉ/i);
  });

  it("does not claim FBT as an executable fulfillment path", () => {
    const serialized = JSON.stringify(createOptimizeProductTimeline());

    expect(serialized).not.toMatch(/Có thể thực thi qua FBT/);
    expect(serialized).not.toMatch(/FBT executable/i);
  });
});

describe("buildOptimizeProductExecution", () => {
  beforeEach(() => {
    resetOptimizeProductExecutionCountersForTests();
  });

  it("returns a deterministic execution id shape and increments on repeat calls", () => {
    const first = buildOptimizeProductExecution();
    const second = buildOptimizeProductExecution();

    expect(first.executionId).toBe("exec-optimize_product_2-1");
    expect(second.executionId).toBe("exec-optimize_product_2-2");
    expect(first.executionId).not.toBe(second.executionId);
  });

  it("seeds workflow 2 with executing lifecycle and a running first action", () => {
    const { record } = buildOptimizeProductExecution();

    expect(record.workflowKey).toBe(OPTIMIZE_PRODUCT_WORKFLOW_KEY);
    expect(record.toolName).toBe(OPTIMIZE_PRODUCT_TOOL_NAME);
    expect(record.lifecycleStatus).toBe("executing");
    expect(record.timeline).toHaveLength(11);
    expect(record.timeline[0]).toMatchObject({
      id: "get-product",
      stepNumber: 1,
      kind: "action",
      status: "running",
    });
    expect(
      record.timeline.slice(1).every((step) => step.status === "pending"),
    ).toBe(true);
  });

  it("records approved input defaults on the execution snapshot", () => {
    const { record } = buildOptimizeProductExecution();
    const defaults = buildOptimizeProductReviewInputDefaults();

    expect(record.approvedInputs.product_id).toBe(defaults.product_id);
    expect(record.approvedInputs.seo_title).toBe(defaults.seo_title);
    expect(record.approvedInputs.price).toBe(defaults.price);
  });
});
