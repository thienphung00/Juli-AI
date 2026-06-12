/**
 * Issue #177 — Shop profile classification + workflow catalog (P1.8-1)
 */
import {
  classifyShopProfile,
  getWorkflowsForProfile,
  PROFILE_BOUNDARY_FIXTURES,
  SHOP_AGE_MID_LARGE_MIN_DAYS,
  GMV_METRICS_MIN_COUNT,
  WORKFLOW_CATALOG,
} from "@/lib/operations";
import {
  loadOperationalModel,
  VALIDATED_WORKFLOW_IDS,
} from "@/lib/mock-data/operations";
import type { UnifiedOperationalDataModel } from "@/lib/mock-data/operations/schemas";

function model(overrides: Partial<UnifiedOperationalDataModel> = {}): UnifiedOperationalDataModel {
  const base = loadOperationalModel("NEW_SHOP");
  return {
    ...base,
    ...overrides,
    shop_metadata: {
      ...base.shop_metadata,
      ...overrides.shop_metadata,
    },
    probation:
      overrides.probation !== undefined
        ? overrides.probation
        : base.probation,
  };
}

describe("Issue #177: classifyShopProfile", () => {
  describe("fixture alignment", () => {
    it("classifies NEW_SHOP fixture as NEW_SHOP", () => {
      expect(classifyShopProfile(loadOperationalModel("NEW_SHOP"))).toBe("NEW_SHOP");
    });

    it("classifies MID_LARGE_SHOP fixture as MID_LARGE_SHOP", () => {
      expect(classifyShopProfile(loadOperationalModel("MID_LARGE_SHOP"))).toBe(
        "MID_LARGE_SHOP",
      );
    });
  });

  describe("threshold documentation", () => {
    it("exports documented classification constants", () => {
      expect(SHOP_AGE_MID_LARGE_MIN_DAYS).toBe(90);
      expect(GMV_METRICS_MIN_COUNT).toBe(2);
    });
  });

  describe("golden boundary fixtures", () => {
    it.each(PROFILE_BOUNDARY_FIXTURES)(
      "$id → $expectedProfile ($note)",
      ({ model: fixtureModel, expectedProfile }) => {
        expect(classifyShopProfile(fixtureModel)).toBe(expectedProfile);
      },
    );
  });

  describe("probation vs graduated boundaries", () => {
    it("routes active probation shops to NEW_SHOP", () => {
      const probationShop = model({
        shop_metadata: {
          shop_id: "shop_probation",
          shop_name: "Probation Shop",
          profile: "NEW_SHOP",
          probation_status: "active",
          graduation_date: null,
          shop_age_days: 120,
        },
      });

      expect(classifyShopProfile(probationShop)).toBe("NEW_SHOP");
    });

    it("routes graduated mid/large shops with 90+ days active to MID_LARGE_SHOP", () => {
      const graduatedShop = loadOperationalModel("MID_LARGE_SHOP");
      expect(graduatedShop.shop_metadata.shop_age_days).toBeGreaterThanOrEqual(
        SHOP_AGE_MID_LARGE_MIN_DAYS,
      );
      expect(classifyShopProfile(graduatedShop)).toBe("MID_LARGE_SHOP");
    });
  });
});

describe("Issue #177: WORKFLOW_CATALOG", () => {
  const GROWTH_LOSS_WORKFLOWS = [
    "budget_optimization",
    "product_scaling",
    "refund_spike_detection",
    "stockout_prevention",
  ] as const;

  const PROBATION_WORKFLOWS = ["npl", "minimize_violations"] as const;

  it("maps NEW_SHOP to probation workflows only", () => {
    const catalog = getWorkflowsForProfile("NEW_SHOP");

    expect(catalog).toEqual(["npl", "minimize_violations"]);
    for (const workflowId of GROWTH_LOSS_WORKFLOWS) {
      expect(catalog).not.toContain(workflowId);
    }
  });

  it("maps MID_LARGE_SHOP to growth and loss-prevention workflows only", () => {
    const catalog = getWorkflowsForProfile("MID_LARGE_SHOP");

    expect(catalog).toEqual([
      "budget_optimization",
      "product_scaling",
      "refund_spike_detection",
      "stockout_prevention",
    ]);
    for (const workflowId of PROBATION_WORKFLOWS) {
      expect(catalog).not.toContain(workflowId);
    }
  });

  it("never references workflow IDs outside ADR-026 stable IDs", () => {
    const allCatalogIds = [
      ...WORKFLOW_CATALOG.NEW_SHOP,
      ...WORKFLOW_CATALOG.MID_LARGE_SHOP,
    ];

    for (const workflowId of allCatalogIds) {
      expect(VALIDATED_WORKFLOW_IDS).toContain(workflowId);
    }

    expect(new Set(allCatalogIds).size).toBe(VALIDATED_WORKFLOW_IDS.length);
  });

  it("covers every validated workflow exactly once across profiles", () => {
    const covered = new Set([
      ...WORKFLOW_CATALOG.NEW_SHOP,
      ...WORKFLOW_CATALOG.MID_LARGE_SHOP,
    ]);

    expect([...covered].sort()).toEqual([...VALIDATED_WORKFLOW_IDS].sort());
  });
});
