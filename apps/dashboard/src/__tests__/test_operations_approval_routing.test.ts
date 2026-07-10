/**
 * Issue #181 — workflow approval routing (P1.8-6)
 */
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { computeHealthCheckResults } from "@/lib/operations/health-check";
import {
  DEFERRED_WORKFLOW_IDS,
  EXECUTABLE_WORKFLOW_IDS,
  getWorkflowExecutionRoute,
  resolveRefundSpikeTaskType,
  resolveTaskForWorkflow,
} from "@/lib/operations/approval-routing";
import { loadOperationalModelForPersona } from "@/lib/mock-data/operations";
import { VALIDATED_WORKFLOW_IDS } from "@/lib/mock-data/operations/schemas";

describe("Issue #181: workflow execution routes", () => {
  it.each(EXECUTABLE_WORKFLOW_IDS)("routes %s to an executable panel", (workflowId) => {
    const route = getWorkflowExecutionRoute(workflowId);
    expect(["listing", "leakage"]).toContain(route);
  });

  it.each(DEFERRED_WORKFLOW_IDS)("routes deferred workflow %s to noop", (workflowId) => {
    expect(getWorkflowExecutionRoute(workflowId)).toBe("noop");
  });

  it("covers every validated workflow id", () => {
    for (const workflowId of VALIDATED_WORKFLOW_IDS) {
      expect(getWorkflowExecutionRoute(workflowId)).toMatch(/listing|leakage|noop/);
    }
  });
});

describe("Issue #181: resolveTaskForWorkflow", () => {
  it("maps npl to list_products task for NEW_SHOP persona", () => {
    const persona = loadPersona("new");
    const health = computeHealthCheckResults(loadOperationalModelForPersona("new"));

    const task = resolveTaskForWorkflow("npl", persona, health);

    expect(task?.type).toBe("list_products");
    expect(task?.id).toBe("task_new_002");
  });

  it("maps refund_spike_detection to return_spike when spike is detected", () => {
    const persona = loadPersona("leakage");
    const health = computeHealthCheckResults(loadOperationalModelForPersona("leakage"));

    expect(health.indicators.refund_spike_indicator.spike_detected).toBe(true);
    expect(resolveRefundSpikeTaskType(health)).toBe("return_spike");

    const task = resolveTaskForWorkflow("refund_spike_detection", persona, health);

    expect(task?.type).toBe("return_spike");
    expect(task?.id).toBe("task_leak_001");
  });

  it("returns null for deferred workflows", () => {
    const persona = loadPersona("new");
    const health = computeHealthCheckResults(loadOperationalModelForPersona("new"));

    expect(resolveTaskForWorkflow("minimize_violations", persona, health)).toBeNull();
    expect(resolveTaskForWorkflow("budget_optimization", persona, health)).toBeNull();
  });
});
