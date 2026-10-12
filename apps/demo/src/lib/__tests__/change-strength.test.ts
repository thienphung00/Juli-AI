import { describe, expect, it } from "vitest";

import { CHANGE_STRENGTH_LABELS, changeStrength, changeStrengthLabel, combinedBand } from "../change-strength";
import table from "./fixtures/change-strength-cases.json";

// D31.7: the same table as tests/unit/test_change_strength.py (backend).
describe("changeStrength (D31.7)", () => {
  it.each(table.cases)("$name", ({ change, a, b, expected }) => {
    expect(changeStrength(change, a, b)).toBe(expected);
  });

  it("combines both windows' bands as √(a² + b²)", () => {
    expect(combinedBand(6, 8)).toBe(10);
    expect(combinedBand(null, 8)).toBeNull();
  });

  it("labels each strength with the on-screen words", () => {
    expect(CHANGE_STRENGTH_LABELS).toEqual({ clear: "Thay đổi rõ", likely: "Có thể thay đổi", noise: "Trong dao động" });
    expect(changeStrengthLabel("likely")).toBe("Có thể thay đổi");
    expect(changeStrengthLabel(null)).toBeNull();
    expect(changeStrengthLabel("other")).toBeNull();
  });
});
