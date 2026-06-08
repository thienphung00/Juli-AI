/**
 * Issue #153 — Mock workflow fixtures (P1.6-1)
 */
import fs from "fs";
import path from "path";
import {
  loadDistributors,
  loadOpportunities,
  loadProductDrafts,
  validateListingFixtures,
  P16_ALLOWED_SOURCES,
} from "@/lib/mock-data/listing-workflow";

const LISTING_WORKFLOW_DIR = path.join(
  process.cwd(),
  "src/lib/mock-data/listing-workflow",
);

describe("Issue #153: listing workflow mock fixtures", () => {
  describe("loadDistributors", () => {
    it("returns at least 5 distributors with stable UUIDs across at least 3 categories", () => {
      const distributors = loadDistributors();

      expect(distributors.length).toBeGreaterThanOrEqual(5);

      const categories = new Set(
        distributors.flatMap((d) => d.category_coverage),
      );
      expect(categories.size).toBeGreaterThanOrEqual(3);

      const ids = distributors.map((d) => d.distributor_id);
      expect(new Set(ids).size).toBe(distributors.length);
      expect(ids).toContain("a1000001-0001-4000-8000-000000000001");
    });

    it("validates required distributor schema fields", () => {
      const result = validateListingFixtures();
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
    });
  });

  describe("loadOpportunities", () => {
    it("returns at least 8 opportunities with deterministic filter fields", () => {
      const opportunities = loadOpportunities();

      expect(opportunities.length).toBeGreaterThanOrEqual(8);

      for (const opportunity of opportunities) {
        expect(opportunity.min_capital_vnd).toBeGreaterThan(0);
        expect(opportunity.max_capital_vnd).toBeGreaterThanOrEqual(
          opportunity.min_capital_vnd,
        );
        expect(opportunity.category.trim().length).toBeGreaterThan(0);
        expect(typeof opportunity.supports_dropship).toBe("boolean");
      }

      const ids = opportunities.map((o) => o.opportunity_id);
      expect(new Set(ids).size).toBe(opportunities.length);
      expect(ids).toContain("b2000001-0001-4000-8000-000000000001");
    });
  });

  describe("loadProductDrafts", () => {
    it("returns golden ProductDraft seeds with required schema fields", () => {
      const drafts = loadProductDrafts();

      expect(drafts.length).toBeGreaterThanOrEqual(1);

      for (const draft of drafts) {
        expect(draft.draft_id).toMatch(
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
        );
        expect(draft.product_info.product_name.trim().length).toBeGreaterThan(0);
        expect(draft.listing_content.title.trim().length).toBeGreaterThan(0);
        expect(draft.compliance.status).toMatch(/^(approved|warning|blocked)$/);
        expect(draft.readiness.overall_score).toBeGreaterThanOrEqual(0);
        expect(draft.readiness.overall_score).toBeLessThanOrEqual(100);
      }

      expect(drafts[0].draft_id).toBe("c3000001-0001-4000-8000-000000000001");
    });
  });

  describe("module contract", () => {
    it("ships MODULE.md documenting listing-workflow loaders", () => {
      const moduleDoc = path.join(LISTING_WORKFLOW_DIR, "MODULE.md");
      expect(fs.existsSync(moduleDoc)).toBe(true);
      const content = fs.readFileSync(moduleDoc, "utf8");
      expect(content).toContain("loadDistributors");
      expect(content).toContain("loadOpportunities");
      expect(content).toContain("loadProductDrafts");
    });

    it("has no TikTok API or Postgres imports in fixture module entrypoint", () => {
      const indexSource = fs.readFileSync(
        path.join(LISTING_WORKFLOW_DIR, "index.ts"),
        "utf8",
      );
      expect(indexSource).not.toMatch(/api-client|@\/lib\/api/);
      expect(indexSource).not.toMatch(/fetch\s*\(|postgres|supabase/i);
    });
  });

  describe("P1.6 source policy", () => {
    it("uses only internal_curated or research sources (no marketplace_api)", () => {
      const distributors = loadDistributors();
      const opportunities = loadOpportunities();

      for (const distributor of distributors) {
        expect(P16_ALLOWED_SOURCES).toContain(distributor.source);
        expect(distributor.source).not.toBe("marketplace_api");
      }

      for (const opportunity of opportunities) {
        expect(P16_ALLOWED_SOURCES).toContain(opportunity.source);
        expect(opportunity.source).not.toBe("marketplace_api");
        expect(opportunity.source).not.toBe("seller_center");
      }
    });
  });
});
