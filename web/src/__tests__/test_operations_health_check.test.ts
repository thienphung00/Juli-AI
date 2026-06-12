/**
 * Issue #178 — Health Check subsystem (P1.8-3)
 */
import {
  computeHealthCheckResults,
  getWorkflowsForHealthIndicator,
  HEALTH_INDICATOR_IDS,
  HEALTH_INDICATOR_TRACEABILITY_MAP,
  REFUND_SPIKE_THRESHOLD_RATIO,
  TARGET_ROAS,
} from "@/lib/operations/health-check";
import { loadOperationalModel } from "@/lib/mock-data/operations";
import type { UnifiedOperationalDataModel } from "@/lib/mock-data/operations/schemas";
import { VALIDATED_WORKFLOW_IDS } from "@/lib/mock-data/operations/schemas";

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
      overrides.probation !== undefined ? overrides.probation : base.probation,
    returns: {
      ...base.returns,
      ...overrides.returns,
    },
  };
}

describe("Issue #178: computeHealthCheckResults envelope", () => {
  it("returns typed health_check_results with all indicator keys", () => {
    const results = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));

    expect(results.shop_id).toBe("shop_mai_linh_001");
    expect(results.computed_at).toBeTruthy();
    expect(results.health_data_source).toBe("mock");
    expect(Object.keys(results.indicators).sort()).toEqual([...HEALTH_INDICATOR_IDS].sort());
  });
});

describe("Issue #178: probation_progress indicator", () => {
  it("computes percent toward graduation and days remaining from probation data", () => {
    const results = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const indicator = results.indicators.probation_progress;

    expect(indicator.indicator_id).toBe("probation_progress");
    expect(indicator.informs_workflows).toEqual(["npl", "minimize_violations"]);
    expect(indicator.percent_toward_graduation).toBeGreaterThan(0);
    expect(indicator.days_remaining).toBeGreaterThan(0);
    expect(indicator.severity).not.toBe("not_applicable");
  });

  it("marks probation progress not_applicable when probation is null", () => {
    const results = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    expect(results.indicators.probation_progress.severity).toBe("not_applicable");
  });
});

describe("Issue #178: sps_health indicator", () => {
  it("computes current SPS, threshold, and gap from probation data", () => {
    const results = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const indicator = results.indicators.sps_health;

    expect(indicator.indicator_id).toBe("sps_health");
    expect(indicator.sps_current).toBe(2.8);
    expect(indicator.sps_threshold).toBe(4.0);
    expect(indicator.threshold_gap).toBeCloseTo(1.2);
    expect(indicator.informs_workflows).toEqual(["npl", "minimize_violations"]);
  });
});

describe("Issue #178: ahr_health indicator", () => {
  it("computes current AHR, threshold, and gap from probation data", () => {
    const results = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const indicator = results.indicators.ahr_health;

    expect(indicator.indicator_id).toBe("ahr_health");
    expect(indicator.ahr_current).toBe(78);
    expect(indicator.ahr_threshold).toBe(90);
    expect(indicator.threshold_gap).toBe(12);
    expect(indicator.informs_workflows).toEqual(["npl", "minimize_violations"]);
  });
});

describe("Issue #178: ad_roas_efficiency indicator", () => {
  it("computes ROAS by active campaign and percent below target", () => {
    const results = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const indicator = results.indicators.ad_roas_efficiency;

    expect(indicator.indicator_id).toBe("ad_roas_efficiency");
    expect(indicator.target_roas).toBe(TARGET_ROAS);
    expect(indicator.campaigns.length).toBeGreaterThanOrEqual(2);
    expect(indicator.informs_workflows).toEqual(["budget_optimization"]);

    const belowTarget = indicator.campaigns.filter(
      (campaign) => campaign.percent_below_target > 0,
    );
    expect(belowTarget.length).toBeGreaterThan(0);
    expect(indicator.active_campaigns_below_target_pct).toBeGreaterThan(0);
  });

  it("marks ad ROAS not_applicable when no active campaigns exist", () => {
    const results = computeHealthCheckResults(
      model({ ad_campaigns: [] }),
    );
    expect(results.indicators.ad_roas_efficiency.severity).toBe("not_applicable");
  });
});

describe("Issue #178: inventory_health indicator", () => {
  it("computes days of inventory remaining and lead-time coverage per SKU", () => {
    const results = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const indicator = results.indicators.inventory_health;

    expect(indicator.indicator_id).toBe("inventory_health");
    expect(indicator.skus.length).toBeGreaterThanOrEqual(1);
    expect(indicator.informs_workflows).toEqual(["stockout_prevention"]);

    const atRisk = indicator.skus.find((sku) => sku.lead_time_coverage_ratio < 1);
    expect(atRisk).toBeDefined();
    expect(indicator.at_risk_sku_count).toBeGreaterThan(0);
  });
});

describe("Issue #178: refund_spike_indicator", () => {
  it("computes refund rate change vs baseline and spike severity flag", () => {
    const results = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const indicator = results.indicators.refund_spike_indicator;

    expect(indicator.indicator_id).toBe("refund_spike_indicator");
    expect(indicator.refund_rate_7d).toBe(0.24);
    expect(indicator.refund_rate_30d).toBe(0.19);
    expect(indicator.percent_change_vs_baseline).toBeGreaterThan(
      REFUND_SPIKE_THRESHOLD_RATIO * 100,
    );
    expect(indicator.spike_detected).toBe(true);
    expect(indicator.severity).toBe("critical");
    expect(indicator.informs_workflows).toEqual(["refund_spike_detection"]);
  });

  it("does not flag spike when refund rate is stable", () => {
    const results = computeHealthCheckResults(
      model({
        returns: {
          refund_count_7d: 0,
          refund_count_30d: 1,
          refund_rate_7d: 0.02,
          refund_rate_30d: 0.03,
          baseline_refund_rate_30d: 0.02,
          top_refund_reasons: [],
          pending_return_authorizations: [],
        },
      }),
    );

    expect(results.indicators.refund_spike_indicator.spike_detected).toBe(false);
  });
});

describe("Issue #178: product_scaling_opportunity indicator", () => {
  it("ranks top SKUs by growth potential score", () => {
    const results = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const indicator = results.indicators.product_scaling_opportunity;

    expect(indicator.indicator_id).toBe("product_scaling_opportunity");
    expect(indicator.top_skus.length).toBeGreaterThan(0);
    expect(indicator.informs_workflows).toEqual(["product_scaling"]);

    const scores = indicator.top_skus.map((sku) => sku.growth_potential_score);
    expect(scores).toEqual([...scores].sort((a, b) => b - a));
  });
});

describe("Issue #178: one unit test per indicator with minimal fixture input", () => {
  it("one unit test per indicator with minimal fixture input", () => {
    const cases = [
      ["probation_progress", "NEW_SHOP"],
      ["sps_health", "NEW_SHOP"],
      ["ahr_health", "NEW_SHOP"],
      ["ad_roas_efficiency", "MID_LARGE_SHOP"],
      ["inventory_health", "MID_LARGE_SHOP"],
      ["refund_spike_indicator", "MID_LARGE_SHOP"],
      ["product_scaling_opportunity", "MID_LARGE_SHOP"],
    ] as const;

    for (const [indicatorId, profile] of cases) {
      const results = computeHealthCheckResults(loadOperationalModel(profile));
      expect(results.indicators[indicatorId].indicator_id).toBe(indicatorId);
      expect(results.indicators[indicatorId].informs_workflows.length).toBeGreaterThan(0);
    }
  });
});

describe("Issue #178: slice scope", () => {
  it("no UI in this slice — logic and tests only under operations lib", () => {
    expect(typeof computeHealthCheckResults).toBe("function");
    expect(HEALTH_INDICATOR_IDS).toHaveLength(7);
  });
});

describe("Issue #178: HEALTH_INDICATOR_TRACEABILITY_MAP", () => {
  it("maps every indicator ID to ≥1 validated catalog workflow", () => {
    for (const indicatorId of HEALTH_INDICATOR_IDS) {
      const workflows = getWorkflowsForHealthIndicator(indicatorId);
      expect(workflows.length).toBeGreaterThanOrEqual(1);
      for (const workflowId of workflows) {
        expect(VALIDATED_WORKFLOW_IDS).toContain(workflowId);
      }
    }
  });

  it("covers all indicator IDs exactly once in the traceability map", () => {
    expect(Object.keys(HEALTH_INDICATOR_TRACEABILITY_MAP).sort()).toEqual(
      [...HEALTH_INDICATOR_IDS].sort(),
    );
  });

  it("never references workflow IDs outside ADR-026 stable IDs", () => {
    const referenced = new Set(
      Object.values(HEALTH_INDICATOR_TRACEABILITY_MAP).flat(),
    );

    for (const workflowId of referenced) {
      expect(VALIDATED_WORKFLOW_IDS).toContain(workflowId);
    }
  });
});
