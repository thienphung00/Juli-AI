/**
 * Issue #164 — Leakage workflow mock fixtures (P1.7-1)
 */
import fs from "fs";
import path from "path";
import {
  loadLeakageFixtures,
  loadLeakageWorkflowTask,
  validateLeakageFixtures,
  LEAKAGE_TASK_TYPES,
} from "@/lib/mock-data/leakage-workflow";
import {
  collectForbiddenPiiKeys,
  isMaskedBuyerId,
} from "@/lib/mock-data/seller-personas/pii";
import { LEAKAGE_PERSONA } from "@/lib/mock-data/seller-personas/fixtures/leakage-persona";

const LEAKAGE_WORKFLOW_DIR = path.join(
  process.cwd(),
  "src/lib/mock-data/leakage-workflow",
);

const REQUIRED_NESTED_FIELDS = [
  "detail",
  "evidence_bundle",
  "root_cause",
  "recommended_action",
  "execution_plan",
  "success",
] as const;

describe("Issue #164: leakage workflow mock fixtures", () => {
  describe("loadLeakageFixtures", () => {
    it("returns exactly four tasks covering all leakage task types", () => {
      const fixtures = loadLeakageFixtures();

      expect(fixtures).toHaveLength(4);

      const types = fixtures.map((task) => task.type).sort();
      expect(types).toEqual([...LEAKAGE_TASK_TYPES].sort());

      const ids = fixtures.map((task) => task.id);
      expect(new Set(ids).size).toBe(4);
      expect(ids).toContain("task_leak_001");
      expect(ids).toContain("task_leak_002");
      expect(ids).toContain("task_leak_003");
      expect(ids).toContain("task_leak_004");
    });

    it("includes required schema fields on every fixture", () => {
      const fixtures = loadLeakageFixtures();

      for (const task of fixtures) {
        expect(task.workflow).toBe("leakage");
        expect(task.copy_source).toBe("mock");
        expect(task.workflow_status).toBe("new");

        for (const field of REQUIRED_NESTED_FIELDS) {
          expect(task[field]).toBeDefined();
        }

        expect(task.detail.summary_vi.trim().length).toBeGreaterThan(0);
        expect(task.root_cause.summary_vi.trim().length).toBeGreaterThan(0);
        expect(task.recommended_action.summary_vi.trim().length).toBeGreaterThan(0);
        expect(task.execution_plan.steps.length).toBeGreaterThanOrEqual(1);
        expect(task.success.headline_vi.trim().length).toBeGreaterThan(0);
        expect(task.success.metrics_vi.length).toBeGreaterThanOrEqual(1);
      }

      const result = validateLeakageFixtures();
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
    });
  });

  describe("loadLeakageWorkflowTask", () => {
    it("returns a single task by stable ID", () => {
      const task = loadLeakageWorkflowTask("task_leak_001");

      expect(task).toBeDefined();
      expect(task!.id).toBe("task_leak_001");
      expect(task!.type).toBe("return_spike");
    });

    it("returns undefined for unknown task IDs", () => {
      expect(loadLeakageWorkflowTask("task_unknown")).toBeUndefined();
    });
  });

  describe("PII guard", () => {
    it("masks buyer IDs in all evidence bundles and forbids raw PII keys", () => {
      const fixtures = loadLeakageFixtures();

      for (const task of fixtures) {
        const bundle = task.evidence_bundle;
        const violations = collectForbiddenPiiKeys(bundle);
        expect(violations).toEqual([]);

        for (const order of bundle.orders) {
          expect(isMaskedBuyerId(order.buyer_id)).toBe(true);
        }
        for (const ret of bundle.returns) {
          expect(isMaskedBuyerId(ret.buyer_id)).toBe(true);
        }
      }
    });
  });

  describe("buyer_cancellation_cluster evidence", () => {
    it("includes cancelled-order rows for buyer-cancellation task", () => {
      const task = loadLeakageWorkflowTask("task_leak_002");
      expect(task).toBeDefined();
      expect(task!.type).toBe("buyer_cancellation_cluster");

      const cancelledOrders = task!.evidence_bundle.orders.filter(
        (order) => order.status === "cancelled",
      );
      expect(cancelledOrders.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe("persona alignment", () => {
    it("leakage-persona task IDs and types match workflow fixtures", () => {
      const fixtures = loadLeakageFixtures();
      const fixtureById = new Map(fixtures.map((task) => [task.id, task]));

      for (const personaTask of LEAKAGE_PERSONA.tasks) {
        const fixture = fixtureById.get(personaTask.id);
        expect(fixture).toBeDefined();
        expect(personaTask.type).toBe(fixture!.type);
      }

      const personaTypes = LEAKAGE_PERSONA.tasks.map((task) => task.type);
      expect(personaTypes).not.toContain("affiliate_fraud");
      expect(personaTypes).not.toContain("policy_update");
      expect(personaTypes).toContain("buyer_cancellation_cluster");
      expect(personaTypes).toContain("return_window_policy");
    });

    it("persona has cancelled orders for buyer_cancellation_cluster evidence refs", () => {
      const cancelTask = LEAKAGE_PERSONA.tasks.find(
        (task) => task.type === "buyer_cancellation_cluster",
      );
      expect(cancelTask).toBeDefined();

      const cancelledInPersona = LEAKAGE_PERSONA.orders.filter(
        (order) => order.status === "cancelled",
      );
      expect(cancelledInPersona.length).toBeGreaterThanOrEqual(2);

      for (const ref of cancelTask!.evidence_refs) {
        if (ref.startsWith("profile:")) continue;
        const order = LEAKAGE_PERSONA.orders.find((o) => o.id === ref);
        if (order) {
          expect(order.status).toBe("cancelled");
        }
      }
    });
  });

  describe("module contract", () => {
    it("ships MODULE.md documenting leakage-workflow loaders", () => {
      const moduleDoc = path.join(LEAKAGE_WORKFLOW_DIR, "MODULE.md");
      expect(fs.existsSync(moduleDoc)).toBe(true);
      const content = fs.readFileSync(moduleDoc, "utf8");
      expect(content).toContain("loadLeakageWorkflowTask");
      expect(content).toContain("loadLeakageFixtures");
    });

    it("has no TikTok API or Postgres imports in fixture module entrypoint", () => {
      const indexSource = fs.readFileSync(
        path.join(LEAKAGE_WORKFLOW_DIR, "index.ts"),
        "utf8",
      );
      expect(indexSource).not.toMatch(/api-client|@\/lib\/api/);
      expect(indexSource).not.toMatch(/fetch\s*\(|postgres|supabase/i);
    });
  });
});
