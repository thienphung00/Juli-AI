import { describe, expect, it } from "vitest";

import {
  CLEAR_EXCESS_TOOL_NAME,
  CLEAR_EXCESS_WORKFLOW_KEY,
  createClearExcessTimeline,
} from "../execution";

describe("createClearExcessTimeline", () => {
  it("maps Workflow 4 to twelve FBS screen-states ending at cleared-outcome", () => {
    const timeline = createClearExcessTimeline();

    expect(timeline).toHaveLength(12);
    expect(timeline.map((step) => step.stepNumber)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
    ]);
    expect(timeline[11]).toMatchObject({
      id: "cleared-outcome",
      stepNumber: 12,
      kind: "outcome",
    });
    expect(timeline.every((step) => step.title.length > 0)).toBe(true);
  });

  it("includes activity wait #39 and inventory reconciliation waits #27 and #68", () => {
    const timeline = createClearExcessTimeline();
    const activityWait = timeline.find((step) => step.id === "activity-status-wait");
    const inventoryWait = timeline.find(
      (step) => step.id === "inventory-reconciliation-wait",
    );

    expect(activityWait?.kind).toBe("wait");
    expect(activityWait?.description).toMatch(/#39/);

    expect(inventoryWait?.kind).toBe("wait");
    expect(inventoryWait?.description).toMatch(/#27/);
    expect(inventoryWait?.description).toMatch(/#68/);
  });

  it("labels zero-floor inventory as an explicit later action and does not claim FBT execution", () => {
    const timeline = createClearExcessTimeline();
    const zeroInventory = timeline.find((step) => step.id === "update-inventory-zero");
    const combinedText = timeline
      .map((step) => `${step.title} ${step.description}`)
      .join(" ");

    expect(zeroInventory?.kind).toBe("action");
    expect(zeroInventory?.description).toMatch(/không thể hoàn tác|xác nhận thực tế/i);

    expect(combinedText).not.toMatch(/FBT.*cập nhật tồn kho|FBT.*Update Inventory/i);
    expect(combinedText).toMatch(/FBS|kho FBS/i);
  });

  it("exports stable workflow identity constants", () => {
    expect(CLEAR_EXCESS_WORKFLOW_KEY).toBe("clear_excess_4");
    expect(CLEAR_EXCESS_TOOL_NAME).toBe("inventory.clear_excess");
  });
});
