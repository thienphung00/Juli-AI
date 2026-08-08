import { describe, expect, it } from "vitest";

import { resolveToneFromDeltaAndGoal } from "../envelope-mapper";

/**
 * Issue #858: Tone must become f(deltaSign, goalDirection)
 *
 * The tone resolver is the single source of tone derivation.
 * It must be called with both the delta sign and the KPI's goal direction.
 */
describe("resolveToneFromDeltaAndGoal", () => {
  describe("higher-is-better KPIs (GMV, AOV, CTOR, LIVE hours)", () => {
    it("resolves rising value (positive delta) to positive tone", () => {
      const tone = resolveToneFromDeltaAndGoal(15, "higher-is-better");
      expect(tone).toBe("positive");
    });

    it("resolves falling value (negative delta) to negative tone", () => {
      const tone = resolveToneFromDeltaAndGoal(-15, "higher-is-better");
      expect(tone).toBe("negative");
    });

    it("resolves zero delta to neutral tone", () => {
      const tone = resolveToneFromDeltaAndGoal(0, "higher-is-better");
      expect(tone).toBe("neutral");
    });
  });

  describe("lower-is-better KPIs (cancellation rate)", () => {
    it("resolves rising value (positive delta) to negative tone", () => {
      const tone = resolveToneFromDeltaAndGoal(10, "lower-is-better");
      expect(tone).toBe("negative");
    });

    it("resolves falling value (negative delta) to positive tone", () => {
      const tone = resolveToneFromDeltaAndGoal(-28, "lower-is-better");
      expect(tone).toBe("positive");
    });

    it("resolves zero delta to neutral tone", () => {
      const tone = resolveToneFromDeltaAndGoal(0, "lower-is-better");
      expect(tone).toBe("neutral");
    });
  });

  describe("edge cases", () => {
    it("handles very small positive values on higher-is-better", () => {
      const tone = resolveToneFromDeltaAndGoal(0.1, "higher-is-better");
      expect(tone).toBe("positive");
    });

    it("handles very small negative values on higher-is-better", () => {
      const tone = resolveToneFromDeltaAndGoal(-0.1, "higher-is-better");
      expect(tone).toBe("negative");
    });

    it("handles very small positive values on lower-is-better", () => {
      const tone = resolveToneFromDeltaAndGoal(0.1, "lower-is-better");
      expect(tone).toBe("negative");
    });

    it("handles very small negative values on lower-is-better", () => {
      const tone = resolveToneFromDeltaAndGoal(-0.1, "lower-is-better");
      expect(tone).toBe("positive");
    });
  });
});
