import { describe, expect, it } from "vitest";

import {
  REPLENISH_INVENTORY_FBT_INTAKE_KEY,
  REPLENISH_INVENTORY_WORKFLOW_KEY,
  createReplenishInventoryTimeline,
} from "../execution";

describe("createReplenishInventoryTimeline", () => {
  it("defines nine FBS screen-states ending at reconciled-outcome", () => {
    const timeline = createReplenishInventoryTimeline();

    expect(timeline).toHaveLength(9);
    expect(timeline.map((step) => step.stepNumber)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9,
    ]);

    const terminal = timeline.at(-1);
    expect(terminal?.id).toBe("reconciled-outcome");
    expect(terminal?.kind).toBe("outcome");
  });

  it("labels the Create PO / Purchase Request step as Unresolved", () => {
    const poStep = createReplenishInventoryTimeline().find(
      (step) => step.id === "create-po-unresolved",
    );

    expect(poStep).toBeDefined();
    expect(poStep?.title).toMatch(/Unresolved/i);
    expect(poStep?.description).toMatch(/Purchase Order|Purchase Request|đơn mua/i);
    expect(poStep?.description).toMatch(/Unresolved|chưa có hợp đồng/i);
  });

  it("marks Supplier/ERP external path as Unresolved and waits on inventory webhooks #27/#68", () => {
    const timeline = createReplenishInventoryTimeline();

    const externalPath = timeline.find((step) => step.id === "external-path-input");
    expect(externalPath?.description).toMatch(/Unresolved/i);
    expect(externalPath?.description).toMatch(/NCC|ERP/i);

    const reconciliationWait = timeline.find(
      (step) => step.id === "inventory-reconciliation-wait",
    );
    expect(reconciliationWait?.kind).toBe("wait");
    expect(reconciliationWait?.description).toMatch(/#27/);
    expect(reconciliationWait?.description).toMatch(/#68/);
  });

  it("does not claim FBT replenish_inventory_3b is executable", () => {
    const timeline = createReplenishInventoryTimeline();
    const joinedCopy = timeline
      .map((step) => `${step.title} ${step.description}`)
      .join(" ");

    expect(REPLENISH_INVENTORY_FBT_INTAKE_KEY).toBe("replenish_inventory_3b");
    expect(joinedCopy).not.toMatch(/Inbound Shipment|FBT inventory update|#24|#21/i);
    expect(joinedCopy).not.toMatch(/có thể thực thi.*FBT/i);
  });

  it("uses the documented FBS workflow key on exported constants", () => {
    expect(REPLENISH_INVENTORY_WORKFLOW_KEY).toBe("replenish_inventory_3");
  });
});
