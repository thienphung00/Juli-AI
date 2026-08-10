import { describe, expect, it } from "vitest";

import { createHeroProductTimeline as timelineViaExecutionsRegistry } from "../../../executions";
import { createHeroProductTimeline } from "../execution";

describe("createHeroProductTimeline", () => {
  it("maps Workflow 1 action, wait, and outcome screen-states to 14 steps", () => {
    const timeline = createHeroProductTimeline();

    expect(timeline).toHaveLength(14);
    expect(timeline.map((step) => step.stepNumber)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
    ]);
    expect(timeline.every((step) => step.title.length > 0)).toBe(true);
  });

  it("includes the product-review wait step before the terminal listed outcome", () => {
    const timeline = createHeroProductTimeline();
    const waitStep = timeline.find((step) => step.kind === "wait");
    const terminal = timeline[timeline.length - 1];

    expect(waitStep?.id).toBe("product-review-wait");
    expect(waitStep?.stepNumber).toBe(12);
    expect(terminal.id).toBe("listed-outcome");
    expect(terminal.kind).toBe("outcome");
  });

  it("is the same timeline the executions registry serves", () => {
    // The stages moved out of executions.ts into this module (ADR-055
    // Consequences); the registry re-exports rather than re-declaring.
    expect(timelineViaExecutionsRegistry).toBe(createHeroProductTimeline);
  });
});
