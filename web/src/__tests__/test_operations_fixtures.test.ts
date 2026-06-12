/**
 * Issue #176 — Unified operational data model fixtures (P1.8-2)
 */
import fs from "fs";
import path from "path";

import {
  assertNoDatumsOutsideSignalRequirements,
  checkTraceability,
  DATUM_TRACEABILITY_MAP,
  exportTraceabilityArtifact,
  getWorkflowsForDatum,
  listOperationalProfiles,
  listTraceabilityDatumKeys,
  loadAllOperationalFixtures,
  loadOperationalModel,
  loadOperationalModelForPersona,
  resolveOperationalProfileForPersona,
  VALIDATED_WORKFLOW_IDS,
  validateOperationsFixtures,
  validateUnifiedOperationalModel,
} from "@/lib/mock-data/operations";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";

const OPERATIONS_DIR = path.join(process.cwd(), "src/lib/mock-data/operations");

describe("Issue #176: unified operational data model fixtures", () => {
  describe("loadOperationalModel", () => {
    it("returns NEW_SHOP fixture with probation signals for npl and minimize_violations", () => {
      const model = loadOperationalModel("NEW_SHOP");

      expect(model.shop_metadata.profile).toBe("NEW_SHOP");
      expect(model.shop_metadata.shop_id).toBe("shop_mai_linh_001");
      expect(model.probation).not.toBeNull();
      expect(model.probation?.violations.length).toBeGreaterThanOrEqual(1);
      expect(model.products.length).toBeGreaterThanOrEqual(1);
      expect(model.health_data_source).toBe("mock");
    });

    it("returns MID_LARGE_SHOP fixture with ads, inventory, and refund spike signals", () => {
      const model = loadOperationalModel("MID_LARGE_SHOP");

      expect(model.shop_metadata.profile).toBe("MID_LARGE_SHOP");
      expect(model.probation).toBeNull();
      expect(model.ad_campaigns.length).toBeGreaterThanOrEqual(2);
      expect(model.returns.refund_rate_7d).toBeGreaterThan(model.returns.baseline_refund_rate_30d);
      expect(model.inventory.some((item) => item.inventory_level <= 20)).toBe(true);
    });
  });

  describe("PersonaSwitcher binding", () => {
    it.each<[PersonaId, "NEW_SHOP" | "MID_LARGE_SHOP"]>([
      ["new", "NEW_SHOP"],
      ["leakage", "MID_LARGE_SHOP"],
      ["growth", "MID_LARGE_SHOP"],
    ])("maps persona %s to profile %s", (personaId, expectedProfile) => {
      expect(resolveOperationalProfileForPersona(personaId)).toBe(expectedProfile);
      expect(loadOperationalModelForPersona(personaId).shop_metadata.profile).toBe(
        expectedProfile,
      );
    });

    it("binds growth persona to MID_LARGE_SHOP with growth shop metadata", () => {
      const model = loadOperationalModelForPersona("growth");
      expect(model.shop_metadata.shop_id).toBe("shop_smarthome_vn_003");
      expect(model.demo_persona_id).toBe("growth");
    });
  });

  describe("schema validation", () => {
    it("validates both profile fixtures without errors", () => {
      const result = validateOperationsFixtures();
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
    });

    it("validates each loaded fixture individually", () => {
      for (const profile of listOperationalProfiles()) {
        const result = validateUnifiedOperationalModel(loadOperationalModel(profile));
        expect(result.valid).toBe(true);
        expect(result.errors).toEqual([]);
      }
    });
  });

  describe("datum→workflow traceability map", () => {
    it("maps every traceability key to at least one validated workflow_id", () => {
      for (const key of listTraceabilityDatumKeys()) {
        const workflows = getWorkflowsForDatum(key);
        expect(workflows.length).toBeGreaterThanOrEqual(1);
        for (const workflowId of workflows) {
          expect(VALIDATED_WORKFLOW_IDS).toContain(workflowId);
        }
      }
    });

    it("asserts every present datum in fixtures maps to ≥1 workflow", () => {
      for (const model of loadAllOperationalFixtures()) {
        const result = checkTraceability(model);
        expect(result.unmappedKeys).toEqual([]);
        expect(result.emptyWorkflowMappings).toEqual([]);
      }
    });

    it("asserts no datum exists outside the six-workflow signal requirements", () => {
      for (const model of loadAllOperationalFixtures()) {
        const outside = assertNoDatumsOutsideSignalRequirements(model);
        expect(outside).toEqual([]);
      }
    });

    it("exports a JSON-serializable traceability artifact", () => {
      const artifact = exportTraceabilityArtifact();
      expect(artifact.version).toBe("1.0.0");
      expect(artifact.workflow_ids).toEqual([...VALIDATED_WORKFLOW_IDS]);
      expect(Object.keys(artifact.datum_map).length).toBe(
        Object.keys(DATUM_TRACEABILITY_MAP).length,
      );
    });
  });

  describe("module contract", () => {
    it("ships MODULE.md documenting operations loaders", () => {
      const moduleDoc = path.join(OPERATIONS_DIR, "MODULE.md");
      expect(fs.existsSync(moduleDoc)).toBe(true);
      const content = fs.readFileSync(moduleDoc, "utf8");
      expect(content).toContain("loadOperationalModel");
      expect(content).toContain("loadOperationalModelForPersona");
      expect(content).toContain("DATUM_TRACEABILITY_MAP");
    });

    it("has no TikTok API or Postgres imports in module entrypoint", () => {
      const indexSource = fs.readFileSync(path.join(OPERATIONS_DIR, "index.ts"), "utf8");
      expect(indexSource).not.toMatch(/api-client|@\/lib\/api/);
      expect(indexSource).not.toMatch(/fetch\s*\(|postgres|supabase/i);
    });
  });
});
