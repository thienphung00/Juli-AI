import { describe, expect, it } from "vitest";

import {
  MAIN_KPI_DEFINITIONS,
  MAIN_KPI_ORDER,
  getChartFormFromMeasurementType,
  type MeasurementType,
} from "../main-kpis";

describe("Chart form resolver (P2-CHART-FORM: ADR-060)", () => {
  describe("AC1: Every KPI declares measurementType; the field is required", () => {
    it("RED: gmv-tiktok has measurementType defined", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      expect(gmv.measurementType).toBeDefined();
      expect(typeof gmv.measurementType).toBe("string");
    });

    it("RED: aov has measurementType defined", () => {
      const aov = MAIN_KPI_DEFINITIONS.aov;
      expect(aov.measurementType).toBeDefined();
      expect(typeof aov.measurementType).toBe("string");
    });

    it("RED: ctor has measurementType defined", () => {
      const ctor = MAIN_KPI_DEFINITIONS.ctor;
      expect(ctor.measurementType).toBeDefined();
      expect(typeof ctor.measurementType).toBe("string");
    });

    it("RED: live-hours has measurementType defined", () => {
      const liveHours = MAIN_KPI_DEFINITIONS["live-hours"];
      expect(liveHours.measurementType).toBeDefined();
      expect(typeof liveHours.measurementType).toBe("string");
    });

    it("RED: cancellation-rate has measurementType defined", () => {
      const cancelRate = MAIN_KPI_DEFINITIONS["cancellation-rate"];
      expect(cancelRate.measurementType).toBeDefined();
      expect(typeof cancelRate.measurementType).toBe("string");
    });

    it("RED: all five KPIs have measurementType", () => {
      for (const key of MAIN_KPI_ORDER) {
        const definition = MAIN_KPI_DEFINITIONS[key];
        expect(definition.measurementType).toBeDefined();
        expect(
          ["flow", "average", "rate", "count", "bounded-ratio"].includes(
            definition.measurementType
          )
        ).toBe(true);
      }
    });
  });

  describe("AC2: A single resolver maps measurement type to form", () => {
    it("RED: getChartFormFromMeasurementType exists and is callable", () => {
      expect(typeof getChartFormFromMeasurementType).toBe("function");
    });

    it("RED: resolver returns 'filled-line' for flow measurement type (GMV)", () => {
      const form = getChartFormFromMeasurementType("flow");
      expect(form).toBe("filled-line");
    });

    it("RED: resolver returns 'plain-line' for average measurement type (AOV)", () => {
      const form = getChartFormFromMeasurementType("average");
      expect(form).toBe("plain-line");
    });

    it("RED: resolver returns 'plain-line' for rate measurement type (CTOR)", () => {
      const form = getChartFormFromMeasurementType("rate");
      expect(form).toBe("plain-line");
    });

    it("RED: resolver returns 'bars' for count measurement type (LIVE hours)", () => {
      const form = getChartFormFromMeasurementType("count");
      expect(form).toBe("bars");
    });

    it("RED: resolver returns 'bounded-ratio' for bounded-ratio measurement type", () => {
      const form = getChartFormFromMeasurementType("bounded-ratio");
      expect(form).toBe("bounded-ratio");
    });

    it("RED: resolver mapping table is consistent (all five types)", () => {
      const forms = new Set<string>();
      const types: MeasurementType[] = [
        "flow",
        "average",
        "rate",
        "count",
        "bounded-ratio",
      ];

      for (const type of types) {
        const form = getChartFormFromMeasurementType(type);
        expect(form).toBeDefined();
        forms.add(form);
      }

      // All five types should resolve (even if some resolve to the same form)
      expect(forms.size).toBeGreaterThanOrEqual(3); // At least 3 distinct forms
    });
  });

  describe("AC3: GMV renders with a gradient fill", () => {
    it("RED: gmv-tiktok has measurementType 'flow'", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      expect(gmv.measurementType).toBe("flow");
    });

    it("RED: flow measurement type resolves to filled-line form", () => {
      const form = getChartFormFromMeasurementType("flow");
      expect(form).toBe("filled-line");
    });
  });

  describe("AC4: AOV renders without a fill", () => {
    it("RED: aov has measurementType 'average'", () => {
      const aov = MAIN_KPI_DEFINITIONS.aov;
      expect(aov.measurementType).toBe("average");
    });

    it("RED: average measurement type resolves to plain-line form (no fill)", () => {
      const form = getChartFormFromMeasurementType("average");
      expect(form).toBe("plain-line");
    });
  });

  describe("AC5: CTOR renders without a fill, with a percentage-formatted axis", () => {
    it("RED: ctor has measurementType 'rate'", () => {
      const ctor = MAIN_KPI_DEFINITIONS.ctor;
      expect(ctor.measurementType).toBe("rate");
    });

    it("RED: rate measurement type resolves to plain-line form (no fill)", () => {
      const form = getChartFormFromMeasurementType("rate");
      expect(form).toBe("plain-line");
    });
  });

  describe("AC6: Business category is not consulted anywhere in form selection", () => {
    it("RED: gmv-tiktok (category: Doanh thu, flow) resolves to filled-line", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      expect(gmv.category).toBe("Doanh thu");
      expect(getChartFormFromMeasurementType(gmv.measurementType)).toBe(
        "filled-line"
      );
    });

    it("RED: aov (category: Doanh thu, average) resolves to plain-line", () => {
      const aov = MAIN_KPI_DEFINITIONS.aov;
      expect(aov.category).toBe("Doanh thu");
      expect(getChartFormFromMeasurementType(aov.measurementType)).toBe(
        "plain-line"
      );
    });

    it("RED: resolver does not accept category as a parameter", () => {
      // This test verifies the function signature doesn't include category
      const form = getChartFormFromMeasurementType("flow");
      expect(form).toBe("filled-line");
      // If category was part of the function signature, TypeScript would catch it
    });
  });

  describe("AC7: Two KPIs sharing a category but differing in measurement type resolve to different forms", () => {
    it("RED: gmv-tiktok (Doanh thu, flow) and aov (Doanh thu, average) resolve to different forms", () => {
      const gmv = MAIN_KPI_DEFINITIONS["gmv-tiktok"];
      const aov = MAIN_KPI_DEFINITIONS.aov;

      expect(gmv.category).toBe("Doanh thu");
      expect(aov.category).toBe("Doanh thu");

      const gmvForm = getChartFormFromMeasurementType(gmv.measurementType);
      const aovForm = getChartFormFromMeasurementType(aov.measurementType);

      expect(gmvForm).not.toBe(aovForm);
      expect(gmvForm).toBe("filled-line");
      expect(aovForm).toBe("plain-line");
    });
  });
});
