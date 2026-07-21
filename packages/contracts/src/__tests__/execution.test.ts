import { describe, expect, it } from "vitest";

import {
  deriveLifecycleFromTimeline,
  type ExecutionTimelineStep,
} from "../execution";

function step(
  overrides: Partial<ExecutionTimelineStep> &
    Pick<ExecutionTimelineStep, "id" | "stepNumber" | "kind" | "title">,
): ExecutionTimelineStep {
  return {
    description: "",
    status: "pending",
    ...overrides,
  };
}

describe("deriveLifecycleFromTimeline", () => {
  it("returns executing when the first action is running", () => {
    const timeline = [
      step({
        id: "get-category",
        stepNumber: 1,
        kind: "action",
        title: "Lấy danh mục",
        status: "running",
      }),
    ];

    expect(deriveLifecycleFromTimeline(timeline)).toBe("executing");
  });

  it("returns needs_input when eligibility outcome failed with recovery", () => {
    const timeline = [
      step({
        id: "eligibility-outcome",
        stepNumber: 3,
        kind: "outcome",
        title: "Điều kiện",
        status: "failed",
        recoveryText: "Bổ sung điều kiện.",
      }),
    ];

    expect(deriveLifecycleFromTimeline(timeline)).toBe("needs_input");
  });

  it("returns completed when the terminal outcome succeeded", () => {
    const timeline = [
      step({
        id: "listed-outcome",
        stepNumber: 14,
        kind: "outcome",
        title: "Đã niêm yết",
        status: "succeeded",
      }),
    ];

    expect(deriveLifecycleFromTimeline(timeline)).toBe("completed");
  });

  it("returns completed when a non-WF1 terminal outcome succeeded", () => {
    const timeline = [
      step({
        id: "live-outcome",
        stepNumber: 11,
        kind: "outcome",
        title: "Đã cập nhật / cần chỉnh",
        status: "succeeded",
      }),
    ];

    expect(deriveLifecycleFromTimeline(timeline)).toBe("completed");
  });
});
