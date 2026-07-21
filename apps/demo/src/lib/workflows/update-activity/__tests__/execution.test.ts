import { beforeEach, describe, expect, it } from "vitest";

import {
  UPDATE_ACTIVITY_TOOL_NAME,
  UPDATE_ACTIVITY_WORKFLOW_KEY,
  buildUpdateActivityExecution,
  createUpdateActivityTimeline,
  resetUpdateActivityExecutionCountersForTests,
} from "../execution";
import { buildUpdateActivityReviewInputDefaults } from "../review";

describe("createUpdateActivityTimeline", () => {
  it("maps Workflow 7c update branch to four FBS steps", () => {
    const timeline = createUpdateActivityTimeline();

    expect(timeline).toHaveLength(4);
    expect(timeline.map((step) => step.stepNumber)).toEqual([1, 2, 3, 4]);
  });

  it("starts with known activity loaded outcome — no search action step", () => {
    const timeline = createUpdateActivityTimeline();

    expect(timeline[0].id).toBe("known-activity-outcome");
    expect(timeline[0].kind).toBe("outcome");
    expect(timeline.some((step) => step.id.includes("search"))).toBe(false);
  });

  it("includes wait for #39 and #63 before terminal outcome", () => {
    const timeline = createUpdateActivityTimeline();
    const waitStep = timeline.find((step) => step.kind === "wait");

    expect(waitStep?.stepNumber).toBe(3);
    expect(waitStep?.description).toMatch(/#39/);
    expect(waitStep?.description).toMatch(/#63/);
  });

  it("ends with updated/partial/rejected terminal outcome", () => {
    const timeline = createUpdateActivityTimeline();
    const terminal = timeline[timeline.length - 1];

    expect(terminal.id).toBe("updated-outcome");
    expect(terminal.kind).toBe("outcome");
  });
});

describe("buildUpdateActivityExecution", () => {
  beforeEach(() => {
    resetUpdateActivityExecutionCountersForTests();
  });

  it("returns deterministic execution ids for workflow 7c", () => {
    const first = buildUpdateActivityExecution();
    const second = buildUpdateActivityExecution();

    expect(first.executionId).toBe("exec-update_activity_7c-1");
    expect(second.executionId).toBe("exec-update_activity_7c-2");
  });

  it("seeds workflow 7c with needs_input lifecycle when known-activity outcome is running", () => {
    const { record } = buildUpdateActivityExecution();

    expect(record.workflowKey).toBe(UPDATE_ACTIVITY_WORKFLOW_KEY);
    expect(record.toolName).toBe(UPDATE_ACTIVITY_TOOL_NAME);
    expect(record.lifecycleStatus).toBe("needs_input");
    expect(record.timeline[0].status).toBe("running");
  });

  it("records read-only activity_id on approved inputs", () => {
    const { record } = buildUpdateActivityExecution();
    const defaults = buildUpdateActivityReviewInputDefaults();

    expect(record.approvedInputs.activity_id).toBe(defaults.activity_id);
  });
});
