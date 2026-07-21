import { beforeEach, describe, expect, it } from "vitest";

import {
  PROCESS_ORDER_TOOL_NAME,
  PROCESS_ORDER_WORKFLOW_KEY,
  buildProcessOrderExecution,
  createProcessOrderTimeline,
  resetProcessOrderExecutionCountersForTests,
} from "../execution";
import { buildProcessOrderReviewInputDefaults } from "../review";

describe("createProcessOrderTimeline", () => {
  it("maps Workflow 5 action, wait, and outcome screen-states to 20 FBS steps", () => {
    const timeline = createProcessOrderTimeline();

    expect(timeline).toHaveLength(20);
    expect(timeline.map((step) => step.stepNumber)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    ]);
    expect(timeline.every((step) => step.title.length > 0)).toBe(true);
  });

  it("includes wait steps for address (#3), AWAITING_SHIPMENT (#1), and package update (#4)", () => {
    const timeline = createProcessOrderTimeline();
    const waits = timeline.filter((step) => step.kind === "wait");

    expect(waits.map((step) => step.id)).toEqual([
      "address-stability-wait",
      "awaiting-shipment-wait",
      "package-update-wait",
    ]);
    expect(waits[0]?.description).toMatch(/#3/);
    expect(waits[1]?.description).toMatch(/#1/);
    expect(waits[2]?.description).toMatch(/#4/);
  });

  it("models the conditional Handle Split Package subflow before create packages", () => {
    const timeline = createProcessOrderTimeline();
    const splitBlock = timeline.slice(5, 12);

    expect(splitBlock.map((step) => step.id)).toEqual([
      "split-attributes",
      "split-branch-outcome",
      "split-orders",
      "search-combinable-packages",
      "combine-package",
      "uncombine-packages",
      "package-update-wait",
    ]);
    expect(timeline.find((step) => step.id === "create-packages")?.stepNumber).toBe(
      13,
    );
  });

  it("models Ship-by-TikTok and Ship-by-Seller as mutually exclusive mock branches", () => {
    const timeline = createProcessOrderTimeline();
    const serialized = JSON.stringify(timeline);

    expect(
      timeline.find((step) => step.id === "get-shipping-document")?.description,
    ).toMatch(/Ship by TikTok/i);
    expect(
      timeline.find((step) => step.id === "get-shipping-document")?.description,
    ).toMatch(/bỏ qua.*Ship by Seller/i);
    expect(
      timeline.find((step) => step.id === "own-carrier-ready")?.description,
    ).toMatch(/Ship by Seller/i);
    expect(
      timeline.find((step) => step.id === "ship-package-tiktok")?.description,
    ).toMatch(/loại trừ.*Ship by Seller/i);
    expect(
      timeline.find((step) => step.id === "batch-ship-seller")?.description,
    ).toMatch(/loại trừ.*Ship by TikTok/i);
    expect(serialized).not.toMatch(/Có thể thực thi qua FBT/);
  });

  it("ends with a shipped terminal outcome step", () => {
    const timeline = createProcessOrderTimeline();
    const terminal = timeline[timeline.length - 1];

    expect(terminal.id).toBe("shipped-outcome");
    expect(terminal.kind).toBe("outcome");
    expect(terminal.stepNumber).toBe(20);
  });
});

describe("buildProcessOrderExecution", () => {
  beforeEach(() => {
    resetProcessOrderExecutionCountersForTests();
  });

  it("returns a deterministic execution id shape and increments on repeat calls", () => {
    const first = buildProcessOrderExecution();
    const second = buildProcessOrderExecution();

    expect(first.executionId).toBe("exec-process_order_5-1");
    expect(second.executionId).toBe("exec-process_order_5-2");
    expect(first.executionId).not.toBe(second.executionId);
  });

  it("seeds workflow 5 with executing lifecycle and a running first action", () => {
    const { record } = buildProcessOrderExecution();

    expect(record.workflowKey).toBe(PROCESS_ORDER_WORKFLOW_KEY);
    expect(record.toolName).toBe(PROCESS_ORDER_TOOL_NAME);
    expect(record.lifecycleStatus).toBe("executing");
    expect(record.timeline).toHaveLength(20);
    expect(record.timeline[0]).toMatchObject({
      id: "get-order-list",
      stepNumber: 1,
      kind: "action",
      status: "running",
    });
    expect(
      record.timeline.slice(1).every((step) => step.status === "pending"),
    ).toBe(true);
  });

  it("records approved input defaults on the execution snapshot", () => {
    const { record } = buildProcessOrderExecution();
    const defaults = buildProcessOrderReviewInputDefaults();

    expect(record.approvedInputs.order_priority).toBe(defaults.order_priority);
    expect(record.approvedInputs.shipping_type).toBe(defaults.shipping_type);
    expect(record.approvedInputs.split_combine).toBe(defaults.split_combine);
  });
});
