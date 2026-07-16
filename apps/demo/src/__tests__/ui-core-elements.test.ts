import { describe, expect, it } from "vitest";

import {
  Badge,
  Button,
  ConfidenceBadge,
  FilterChip,
  HealthBar,
  InputChip,
  ProgressBar,
  RealEstimatedProgressBar,
  StatusChip,
} from "@juli/ui";

describe("Demo import boundary for @juli/ui core elements", () => {
  it("imports all core element exports from the shared package", () => {
    expect(Button).toBeTypeOf("function");
    expect(Badge).toBeTypeOf("function");
    expect(ConfidenceBadge).toBeTypeOf("function");
    expect(StatusChip).toBeTypeOf("function");
    expect(FilterChip).toBeTypeOf("function");
    expect(InputChip).toBeTypeOf("function");
    expect(ProgressBar).toBeTypeOf("function");
    expect(RealEstimatedProgressBar).toBeTypeOf("function");
    expect(HealthBar).toBeTypeOf("function");
  });
});
