/**
 * Issue #156 — ProductDraft CSV/JSON export (P1.6-4)
 */
import { PRODUCT_DRAFTS } from "@/lib/mock-data/listing-workflow/fixtures/product-drafts";
import {
  ExportBlockedError,
  exportProductDraft,
} from "@/lib/workflows/new-seller/listing/export";

const readyDraft = PRODUCT_DRAFTS[0]!;
const blockedDraft = PRODUCT_DRAFTS[1]!;

describe("Issue #156: exportProductDraft", () => {
  describe("JSON export", () => {
    it("returns parseable JSON with required ProductDraft fields", () => {
      const result = exportProductDraft(readyDraft, "json");

      expect(result.mimeType).toBe("application/json");
      expect(result.filename).toMatch(/\.json$/);

      const parsed = JSON.parse(result.content) as Record<string, unknown>;
      expect(parsed.draft_id).toBe(readyDraft.draft_id);
      expect(parsed.product_info).toEqual(readyDraft.product_info);
      expect(parsed.listing_content).toEqual(readyDraft.listing_content);
      expect(parsed.compliance).toEqual(readyDraft.compliance);
      expect(parsed.readiness).toEqual(readyDraft.readiness);
    });
  });

  describe("CSV export", () => {
    it("returns valid CSV with schema field headers", () => {
      const result = exportProductDraft(readyDraft, "csv");

      expect(result.mimeType).toBe("text/csv");
      expect(result.filename).toMatch(/\.csv$/);

      const lines = result.content.trim().split("\n");
      expect(lines.length).toBeGreaterThanOrEqual(2);

      const headers = lines[0]!.split(",");
      expect(headers).toContain("draft_id");
      expect(headers).toContain("product_info.product_name");
      expect(headers).toContain("compliance.status");
      expect(headers).toContain("readiness.overall_score");

      const values = lines[1]!.split(",");
      expect(values[headers.indexOf("draft_id")]).toBe(readyDraft.draft_id);
    });
  });

  describe("blocked draft guard", () => {
    it("throws ExportBlockedError when compliance.status is blocked", () => {
      expect(() => exportProductDraft(blockedDraft, "json")).toThrow(
        ExportBlockedError,
      );
      expect(() => exportProductDraft(blockedDraft, "csv")).toThrow(
        ExportBlockedError,
      );
    });
  });
});
