import { beforeEach, describe, expect, it } from "vitest";

import {
  DELETE_ACTIVITY_TOOL_NAME,
  DELETE_ACTIVITY_WORKFLOW_KEY,
  buildDeleteActivityExecution,
  createDeleteActivityTimeline,
  resetDeleteActivityExecutionCountersForTests,
} from "../execution";
import { buildDeleteActivityReviewInputDefaults } from "../review";

describe("createDeleteActivityTimeline", () => {
  it("maps Workflow 7b end branch to five FBS steps", () => {
    const timeline = createDeleteActivityTimeline();

    expect(timeline).toHaveLength(5);
    expect(timeline.map((step) => step.stepNumber)).toEqual([1, 2, 3, 4, 5]);
  });

  it("follows Get Activity → end eligibility → deactivate → wait → outcome", () => {
    const timeline = createDeleteActivityTimeline();

    expect(timeline.map((step) => step.id)).toEqual([
      "get-activity",
      "end-eligibility-outcome",
      "deactivate-activity",
      "deactivation-wait",
      "inactive-outcome",
    ]);
  });

  it("includes wait for Activity status change webhook #39", () => {
    const waitStep = createDeleteActivityTimeline().find(
      (step) => step.kind === "wait",
    );

    expect(waitStep?.id).toBe("deactivation-wait");
    expect(waitStep?.description).toMatch(/#39/);
  });

  it("notes inactive no-op path in end eligibility outcome", () => {
    const outcome = createDeleteActivityTimeline().find(
      (step) => step.id === "end-eligibility-outcome",
    );

    expect(outcome?.description).toMatch(/inactive|no-op/i);
  });

  it("ends with inactive/still active/failed terminal outcome", () => {
    const terminal = createDeleteActivityTimeline().at(-1);

    expect(terminal?.id).toBe("inactive-outcome");
    expect(terminal?.kind).toBe("outcome");
  });
});

describe("buildDeleteActivityExecution", () => {
  beforeEach(() => {
    resetDeleteActivityExecutionCountersForTests();
  });

  it("returns deterministic execution ids for workflow 7b", () => {
    const first = buildDeleteActivityExecution();
    const second = buildDeleteActivityExecution();

    expect(first.executionId).toBe("exec-delete_activity_7b-1");
    expect(second.executionId).toBe("exec-delete_activity_7b-2");
  });

  it("seeds workflow 7b with executing lifecycle and running Get Activity", () => {
    const { record } = buildDeleteActivityExecution();

    expect(record.workflowKey).toBe(DELETE_ACTIVITY_WORKFLOW_KEY);
    expect(record.toolName).toBe(DELETE_ACTIVITY_TOOL_NAME);
    expect(record.lifecycleStatus).toBe("executing");
    expect(record.timeline[0]).toMatchObject({
      id: "get-activity",
      kind: "action",
      status: "running",
    });
  });

  it("records confirmation-only approved inputs", () => {
    const { record } = buildDeleteActivityExecution();
    const defaults = buildDeleteActivityReviewInputDefaults();

    expect(record.approvedInputs.activity_id).toBe(defaults.activity_id);
    expect(record.approvedInputs.confirm_end).toBe("");
    expect(Object.keys(record.approvedInputs)).toEqual([
      "activity_id",
      "confirm_end",
    ]);
  });
});
