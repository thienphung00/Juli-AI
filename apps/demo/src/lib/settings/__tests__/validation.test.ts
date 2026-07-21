import { describe, expect, it } from "vitest";

import { workflowTemplateFixtures } from "../fixtures";
import {
  getEffectiveSettingsValue,
  validateSettingsField,
} from "../validation";

describe("settings field validation", () => {
  const replenishTemplate = workflowTemplateFixtures.find(
    (template) => template.workflowKey === "replenish_inventory_3", // gitleaks:allow
  );

  it("validates allowed numeric ranges for editable thresholds", () => {
    const field = replenishTemplate?.fields.find(
      (entry) => entry.key === "reorder_days_threshold",
    );

    expect(field).toBeDefined();
    expect(validateSettingsField(field!, "4")).toBeNull();
    expect(validateSettingsField(field!, "2")).toMatch(/3–30 ngày/);
    expect(validateSettingsField(field!, "31")).toMatch(/3–30 ngày/);
  });

  it("merges saved values over defaults without mutating fixtures", () => {
    const field = replenishTemplate!.fields.find(
      (entry) => entry.key === "reorder_days_threshold",
    )!;

    expect(
      getEffectiveSettingsValue(field, {}, { "replenish_inventory_3:reorder_days_threshold": "10" }, "replenish_inventory_3:reorder_days_threshold"),
    ).toBe("10");
    expect(field.defaultValue).not.toBe("10");
  });
});
