import { describe, expect, it } from "vitest";

import type { MainKpiDefinition } from "../main-kpis";
import { MAIN_KPI_DEFINITIONS, MAIN_KPI_ORDER } from "../main-kpis";

describe("Issue #867: ChartKind retirement (P2-CHART-RETIRE)", () => {
  describe("AC1: ChartKind type no longer exists in the type surface", () => {
    it("RED: no KPI definition has a chartKind field", () => {
      // After retirement, chartKind should be completely gone from KPI definitions
      for (const key of MAIN_KPI_ORDER) {
        const definition = MAIN_KPI_DEFINITIONS[key];
        expect(definition).toHaveProperty("measurementType");
        expect(definition).toHaveProperty("goalDirection");
        // chartKind should NOT exist on the definition
        expect(definition).not.toHaveProperty("chartKind");
      }
    });
  });

  describe("AC2: every KPI renders a form derived from its measurement type", () => {
    it("RED: all five KPIs have a measurementType", () => {
      const measurementTypes = [
        "flow",
        "average",
        "rate",
        "count",
        "bounded-ratio",
      ] as const;

      for (const key of MAIN_KPI_ORDER) {
        const definition = MAIN_KPI_DEFINITIONS[key];
        expect(measurementTypes).toContain(definition.measurementType);
      }
    });

    it("RED: gmv-tiktok is flow (sum-able quantity)", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      expect(gmv.measurementType).toBe("flow");
    });

    it("RED: aov is average", () => {
      const aov = MAIN_KPI_DEFINITIONS.aov;
      expect(aov.measurementType).toBe("average");
    });

    it("RED: ctor is rate", () => {
      const ctor = MAIN_KPI_DEFINITIONS.ctor;
      expect(ctor.measurementType).toBe("rate");
    });

    it("RED: live-hours is count", () => {
      const liveHours = MAIN_KPI_DEFINITIONS["live-hours"];
      expect(liveHours.measurementType).toBe("count");
    });

    it("RED: cancellation-rate is bounded-ratio", () => {
      const cancelRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      expect(cancelRate.measurementType).toBe("bounded-ratio");
    });
  });
});
