import { describe, expect, it, beforeEach } from "vitest";

import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  CREATE_HERO_PRODUCT_TOOL_NAME,
  createHeroProductTimeline,
  resetExecutionCountersForTests,
  startExecution,
} from "../executions";

describe("startExecution", () => {
  beforeEach(() => {
    resetExecutionCountersForTests();
  });

  it("returns a deterministic execution id shape and increments on repeat calls", () => {
    const first = startExecution(CREATE_HERO_PRODUCT_WORKFLOW_KEY);
    const second = startExecution(CREATE_HERO_PRODUCT_WORKFLOW_KEY);

    expect(first.executionId).toBe("exec-create_hero_product_1-1");
    expect(second.executionId).toBe("exec-create_hero_product_1-2");
    expect(first.executionId).not.toBe(second.executionId);
  });

  it("seeds workflow 1 with executing lifecycle and a running first action", () => {
    const { record } = startExecution(CREATE_HERO_PRODUCT_WORKFLOW_KEY);

    expect(record.workflowKey).toBe(CREATE_HERO_PRODUCT_WORKFLOW_KEY);
    expect(record.toolName).toBe(CREATE_HERO_PRODUCT_TOOL_NAME);
    expect(record.lifecycleStatus).toBe("executing");
    expect(record.timeline).toHaveLength(14);
    expect(record.timeline[0]).toMatchObject({
      id: "get-category",
      stepNumber: 1,
      kind: "action",
      status: "running",
    });
    expect(record.timeline.slice(1).every((step) => step.status === "pending")).toBe(
      true,
    );
  });

  it("includes an approved input snapshot for downstream detail rendering", () => {
    const { record } = startExecution(CREATE_HERO_PRODUCT_WORKFLOW_KEY);

    expect(record.approvedInputs.category_id).toBeTruthy();
    expect(record.approvedInputs.warehouse_id).toBeTruthy();
    expect(record.approvedInputs.price).toBeTruthy();
  });

  it("rejects unsupported workflow keys", () => {
    expect(() => startExecution("optimize_product_2")).toThrow(/Unsupported workflow key/);
  });
});

describe("createHeroProductTimeline", () => {
  it("maps the 14 FBS numbered states with Vietnamese labels", () => {
    const timeline = createHeroProductTimeline();

    expect(timeline.map((step) => step.stepNumber)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
    ]);
    expect(timeline[11].kind).toBe("wait");
    expect(timeline[13].kind).toBe("outcome");
    expect(timeline.every((step) => step.title.length > 0)).toBe(true);
  });
});
