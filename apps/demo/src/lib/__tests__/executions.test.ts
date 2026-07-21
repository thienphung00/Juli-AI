import { describe, expect, it, beforeEach } from "vitest";

import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  CREATE_HERO_PRODUCT_TOOL_NAME,
  PREVENT_CANCELLATION_TOOL_NAME,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_REFUND_TOOL_NAME,
  PREVENT_REFUND_WORKFLOW_KEY,
  PREVENT_RETURN_FBT_INTAKE_KEY,
  PREVENT_RETURN_TOOL_NAME,
  PREVENT_RETURN_WORKFLOW_KEY,
  createHeroProductTimeline,
  createPreventCancellationTimeline,
  createPreventRefundTimeline,
  createPreventReturnTimeline,
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

  it("records caller-supplied review drafts on the approvedInputs snapshot", () => {
    const { record } = startExecution(CREATE_HERO_PRODUCT_WORKFLOW_KEY, {
      brand_id: "BR-9999 — Thương hiệu thử",
      price: "315000",
    });

    expect(record.approvedInputs.brand_id).toBe("BR-9999 — Thương hiệu thử");
    expect(record.approvedInputs.price).toBe("315000");
    expect(record.approvedInputs.category_id).toBe("700648");
    expect(record.approvedInputs.warehouse_id).toBe("WH-FBS-HCM-01");
  });

  it("starts workflow 2 with optimize_product tool and eleven-step timeline", () => {
    const { executionId, record } = startExecution("optimize_product_2");

    expect(executionId).toBe("exec-optimize_product_2-1");
    expect(record.toolName).toBe("listing.optimize_product");
    expect(record.lifecycleStatus).toBe("executing");
    expect(record.timeline).toHaveLength(11);
    expect(record.timeline[0]?.status).toBe("running");
  });

  it("starts workflow 5 with fulfillment.process_order tool and twenty-step timeline", () => {
    const { executionId, record } = startExecution("process_order_5");

    expect(executionId).toBe("exec-process_order_5-1");
    expect(record.toolName).toBe("fulfillment.process_order");
    expect(record.lifecycleStatus).toBe("executing");
    expect(record.timeline).toHaveLength(20);
    expect(record.timeline[0]?.status).toBe("running");
  });

  it("rejects unsupported workflow keys including FBT intake scaffold", () => {
    expect(() => startExecution("not_a_real_workflow_key")).toThrow(
      /Unsupported workflow key/,
    );
    expect(() => startExecution(PREVENT_RETURN_FBT_INTAKE_KEY)).toThrow(
      /Unsupported workflow key/,
    );
  });

  it.each([
    {
      workflowKey: PREVENT_CANCELLATION_WORKFLOW_KEY,
      toolName: PREVENT_CANCELLATION_TOOL_NAME,
      stepCount: 10,
    },
    {
      workflowKey: PREVENT_RETURN_WORKFLOW_KEY,
      toolName: PREVENT_RETURN_TOOL_NAME,
      stepCount: 15,
    },
    {
      workflowKey: PREVENT_REFUND_WORKFLOW_KEY,
      toolName: PREVENT_REFUND_TOOL_NAME,
      stepCount: 10,
    },
  ])(
    "seeds $workflowKey with executing lifecycle and correct tool_name",
    ({ workflowKey, toolName, stepCount }) => {
      const { executionId, record } = startExecution(workflowKey);

      expect(executionId).toBe(`exec-${workflowKey}-1`);
      expect(record.toolName).toBe(toolName);
      expect(record.lifecycleStatus).toBe("executing");
      expect(record.timeline).toHaveLength(stepCount);
      expect(record.timeline[0].status).toBe("running");
      expect(record.approvedInputs.seller_decision).toBe("");
    },
  );
});

describe("createHeroProductTimeline", () => {
  it("maps Workflow 1 action, wait, outcome, recovery, and rollback states to 14 FBS steps", () => {
    const timeline = createHeroProductTimeline();

    expect(timeline.map((step) => step.stepNumber)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
    ]);
    expect(timeline[11].kind).toBe("wait");
    expect(timeline[13].kind).toBe("outcome");
    expect(timeline.every((step) => step.title.length > 0)).toBe(true);
  });
});

describe("post-sales timelines", () => {
  it("maps cancellation, return, and refund evidence/wait/outcome/recovery states", () => {
    expect(createPreventCancellationTimeline()).toHaveLength(10);
    expect(createPreventReturnTimeline()).toHaveLength(15);
    expect(createPreventRefundTimeline()).toHaveLength(10);

    expect(createPreventCancellationTimeline()[8].kind).toBe("wait");
    expect(createPreventReturnTimeline()[11].title).toMatch(/nhập lại kho/i);
    expect(createPreventRefundTimeline()[8].recoveryText).toMatch(
      /Không xác nhận tiền đã chuyển/,
    );
  });
});
