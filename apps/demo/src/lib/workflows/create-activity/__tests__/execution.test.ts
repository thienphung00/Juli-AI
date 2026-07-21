import { beforeEach, describe, expect, it } from "vitest";

import {
  CREATE_ACTIVITY_TOOL_NAME,
  CREATE_ACTIVITY_WORKFLOW_KEY,
  buildCreateActivityExecution,
  createCreateActivityTimeline,
  resetCreateActivityExecutionCountersForTests,
} from "../execution";
import { buildCreateActivityReviewInputDefaults } from "../review";

describe("createCreateActivityTimeline", () => {
  it("maps Workflow 7a create branch to five FBS steps", () => {
    const timeline = createCreateActivityTimeline();

    expect(timeline).toHaveLength(5);
    expect(timeline.map((step) => step.stepNumber)).toEqual([1, 2, 3, 4, 5]);
    expect(timeline.every((step) => step.title.length > 0)).toBe(true);
  });

  it("starts with create eligibility outcome before create and attach actions", () => {
    const timeline = createCreateActivityTimeline();

    expect(timeline[0].id).toBe("create-eligibility-outcome");
    expect(timeline[0].kind).toBe("outcome");
    expect(timeline[1].id).toBe("create-activity");
    expect(timeline[2].id).toBe("update-activity-product");
  });

  it("includes a wait step for Activity status change webhook #39", () => {
    const timeline = createCreateActivityTimeline();
    const waitStep = timeline.find((step) => step.kind === "wait");

    expect(waitStep?.stepNumber).toBe(4);
    expect(waitStep?.id).toBe("activity-live-wait");
    expect(waitStep?.description).toMatch(/#39/);
  });

  it("ends with active/partial/rejected terminal outcome", () => {
    const timeline = createCreateActivityTimeline();
    const terminal = timeline[timeline.length - 1];

    expect(terminal.id).toBe("active-outcome");
    expect(terminal.kind).toBe("outcome");
    expect(terminal.stepNumber).toBe(5);
  });

  it("does not claim FBT as an executable promotion path", () => {
    const serialized = JSON.stringify(createCreateActivityTimeline());

    expect(serialized).not.toMatch(/Có thể thực thi qua FBT/);
    expect(serialized).not.toMatch(/FBT executable/i);
  });
});

describe("buildCreateActivityExecution", () => {
  beforeEach(() => {
    resetCreateActivityExecutionCountersForTests();
  });

  it("returns a deterministic execution id shape and increments on repeat calls", () => {
    const first = buildCreateActivityExecution();
    const second = buildCreateActivityExecution();

    expect(first.executionId).toBe("exec-create_activity_7a-1");
    expect(second.executionId).toBe("exec-create_activity_7a-2");
  });

  it("seeds workflow 7a with needs_input lifecycle when eligibility outcome is running", () => {
    const { record } = buildCreateActivityExecution();

    expect(record.workflowKey).toBe(CREATE_ACTIVITY_WORKFLOW_KEY);
    expect(record.toolName).toBe(CREATE_ACTIVITY_TOOL_NAME);
    expect(record.lifecycleStatus).toBe("needs_input");
    expect(record.timeline[0]).toMatchObject({
      id: "create-eligibility-outcome",
      stepNumber: 1,
      kind: "outcome",
      status: "running",
    });
  });

  it("records approved input defaults on the execution snapshot", () => {
    const { record } = buildCreateActivityExecution();
    const defaults = buildCreateActivityReviewInputDefaults();

    expect(record.approvedInputs.skus).toBe(defaults.skus);
    expect(record.approvedInputs.discount_config).toBe("");
  });
});
