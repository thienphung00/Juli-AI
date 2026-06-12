/**
 * Issue #182 — workflow_outcome_metrics fixtures + ADR-026 Appendix B criteria (P1.8-7)
 */
import {
  loadAllWorkflowOutcomeMetrics,
  loadWorkflowOutcomeMetrics,
  OUTCOME_CADENCE_IDS,
  WORKFLOW_OUTCOME_SUCCESS_CRITERIA,
} from "@/lib/operations/outcome-metrics";
import { VALIDATED_WORKFLOW_IDS } from "@/lib/mock-data/operations/schemas";

describe("Issue #182: WORKFLOW_OUTCOME_SUCCESS_CRITERIA", () => {
  it.each(VALIDATED_WORKFLOW_IDS)("defines ADR-026 Appendix B criteria for %s", (workflowId) => {
    const criteria = WORKFLOW_OUTCOME_SUCCESS_CRITERIA[workflowId];
    expect(criteria.metric).toBeTruthy();
    expect(criteria.period).toBeTruthy();
    expect(criteria.threshold).toBeTruthy();
  });

  it("matches ADR-026 Appendix B table exactly", () => {
    expect(WORKFLOW_OUTCOME_SUCCESS_CRITERIA.npl).toEqual({
      metric: "SPS change",
      period: "7d post-publish",
      threshold: "≥ +5 SPS points",
    });
    expect(WORKFLOW_OUTCOME_SUCCESS_CRITERIA.minimize_violations).toEqual({
      metric: "AHR improvement / violation count",
      period: "7d",
      threshold: "≥ +10 AHR points OR violation count ↓",
    });
    expect(WORKFLOW_OUTCOME_SUCCESS_CRITERIA.budget_optimization).toEqual({
      metric: "ROAS / revenue change",
      period: "7d",
      threshold: "ROAS +15% OR revenue +10%",
    });
    expect(WORKFLOW_OUTCOME_SUCCESS_CRITERIA.product_scaling).toEqual({
      metric: "Revenue per scaled SKU",
      period: "14d",
      threshold: "≥ +20% revenue for scaled products",
    });
    expect(WORKFLOW_OUTCOME_SUCCESS_CRITERIA.refund_spike_detection).toEqual({
      metric: "Refund rate reduction",
      period: "7d",
      threshold: "Refund rate returns to baseline",
    });
    expect(WORKFLOW_OUTCOME_SUCCESS_CRITERIA.stockout_prevention).toEqual({
      metric: "Stockouts avoided",
      period: "30d",
      threshold: "0 unplanned stockouts",
    });
  });
});

describe("Issue #182: loadWorkflowOutcomeMetrics envelope", () => {
  it("returns typed mock envelope per validated workflow", () => {
    for (const workflowId of VALIDATED_WORKFLOW_IDS) {
      const envelope = loadWorkflowOutcomeMetrics(workflowId, {
        executedAt: "2026-06-12T10:00:00.000Z",
      });

      expect(envelope.workflow_id).toBe(workflowId);
      expect(envelope.workflow_name).toBeTruthy();
      expect(envelope.executed_at).toBe("2026-06-12T10:00:00.000Z");
      expect(envelope.success_criteria).toEqual(
        WORKFLOW_OUTCOME_SUCCESS_CRITERIA[workflowId],
      );
      expect(envelope.cadences).toHaveLength(OUTCOME_CADENCE_IDS.length);
      expect(envelope.cadences.map((slice) => slice.cadence)).toEqual([
        ...OUTCOME_CADENCE_IDS,
      ]);
    }
  });

  it("loadAllWorkflowOutcomeMetrics covers all six workflows", () => {
    const all = loadAllWorkflowOutcomeMetrics();
    expect(all).toHaveLength(VALIDATED_WORKFLOW_IDS.length);
    expect(all.map((item) => item.workflow_id).sort()).toEqual(
      [...VALIDATED_WORKFLOW_IDS].sort(),
    );
  });

  it("realtime cadence includes execution_status for every workflow", () => {
    for (const workflowId of VALIDATED_WORKFLOW_IDS) {
      const realtime = loadWorkflowOutcomeMetrics(workflowId).cadences.find(
        (slice) => slice.cadence === "realtime",
      );
      expect(realtime?.execution_status).toBeTruthy();
      expect(realtime?.readings.length).toBeGreaterThan(0);
    }
  });
});
