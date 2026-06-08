/**
 * Issue #154 — Rules-based listing generation (P1.6-3)
 */
import {
  canExportProductDraft,
  generateProductDraft,
  READINESS_EXPORT_THRESHOLD,
  BLOCKING_ISSUE_MISSING_PRICE,
  BLOCKING_ISSUE_BLOCKED_CATEGORY,
} from "@/lib/workflows/new-seller/listing";
import type { OpportunityCardContext } from "@/lib/workflows/new-seller/listing";
import { DISTRIBUTORS } from "@/lib/mock-data/listing-workflow/fixtures/distributors";
import { OPPORTUNITIES } from "@/lib/mock-data/listing-workflow/fixtures/opportunities";

const SELLER_ID = "seller_demo_new_001";
const SHOP_ID = "shop_mai_linh_001";

describe("Issue #154: listing rules engine", () => {
  describe("compliance — blocked category", () => {
    it("blocks export when category is on the blocklist", () => {
      const draft = generateProductDraft({
        source_type: "manual_form",
        seller_id: SELLER_ID,
        shop_id: SHOP_ID,
        product_name: "Súng hơi mini",
        category: "Vũ khí",
        price: 250_000,
        brand: "TestBrand",
        description: "Mô tả sản phẩm bị cấm.",
      });

      expect(draft.compliance.status).toBe("blocked");
      expect(draft.compliance.blocking_issues).toContain(
        BLOCKING_ISSUE_BLOCKED_CATEGORY,
      );
      expect(draft.status).toBe("blocked");
      expect(canExportProductDraft(draft)).toBe(false);
    });
  });

  describe("compliance — missing price", () => {
    it("adds a blocking issue when price is missing or zero", () => {
      const draft = generateProductDraft({
        source_type: "manual_form",
        seller_id: SELLER_ID,
        shop_id: SHOP_ID,
        product_name: "Tai nghe Bluetooth",
        category: "Điện tử",
        price: 0,
      });

      expect(draft.compliance.status).toBe("blocked");
      expect(draft.compliance.blocking_issues).toContain(
        BLOCKING_ISSUE_MISSING_PRICE,
      );
      expect(canExportProductDraft(draft)).toBe(false);
    });
  });

  describe("readiness — complete valid input", () => {
    it("returns ready_for_export with score at or above the documented threshold", () => {
      const draft = generateProductDraft({
        source_type: "manual_form",
        seller_id: SELLER_ID,
        shop_id: SHOP_ID,
        product_name: "Serum Vitamin C 20ml",
        category: "Mỹ phẩm",
        price: 189_000,
        brand: "Mai Linh Beauty",
        variants: ["20ml"],
        description: "Serum vitamin C giúp làm sáng da và giảm thâm nám.",
      });

      expect(draft.compliance.status).toBe("approved");
      expect(draft.status).toBe("ready_for_export");
      expect(draft.readiness.overall_score).toBeGreaterThanOrEqual(
        READINESS_EXPORT_THRESHOLD,
      );
      expect(draft.product_info.product_name).toBe("Serum Vitamin C 20ml");
      expect(draft.listing_content.title).toContain("Serum Vitamin C 20ml");
      expect(draft.listing_content.bullet_points.length).toBeGreaterThanOrEqual(3);
      expect(canExportProductDraft(draft)).toBe(true);
    });
  });

  describe("determinism", () => {
    it("produces identical drafts for the same input context", () => {
      const context = {
        source_type: "manual_form" as const,
        seller_id: SELLER_ID,
        shop_id: SHOP_ID,
        product_name: "Áo thun basic cotton",
        category: "Thời trang",
        price: 99_000,
        brand: "TrendWear",
        description: "Áo thun cotton thoáng mát.",
      };

      const first = generateProductDraft(context);
      const second = generateProductDraft(context);

      expect(first).toEqual(second);
    });
  });

  describe("url_stub extraction", () => {
    it("extracts product name and category hints without live fetch", () => {
      const draft = generateProductDraft({
        source_type: "url_stub",
        seller_id: SELLER_ID,
        shop_id: SHOP_ID,
        url_stub: "https://shop.example.com/beauty/serum-vitamin-c-20ml",
        price: 175_000,
        brand: "GlowLab",
      });

      expect(draft.source_type).toBe("url_stub");
      expect(draft.product_info.category).toBe("Mỹ phẩm");
      expect(draft.product_info.product_name).toContain("Serum");
      expect(draft.listing_content.seo_keywords.length).toBeGreaterThan(0);
    });
  });

  describe("opportunity_card extraction", () => {
    it("pre-fills draft from opportunity and distributor context", () => {
      const opportunity = OPPORTUNITIES[0];
      const distributor = DISTRIBUTORS[0];
      const context: OpportunityCardContext = {
        source_type: "opportunity_card",
        seller_id: SELLER_ID,
        shop_id: SHOP_ID,
        opportunity,
        distributor,
        price: 200_000,
      };

      const draft = generateProductDraft(context);

      expect(draft.source_type).toBe("opportunity_card");
      expect(draft.product_info.product_name).toBe(opportunity.product_name);
      expect(draft.product_info.category).toBe(opportunity.category);
      expect(draft.product_info.brand).toBe(distributor.name);
      expect(draft.product_info.price).toBe(200_000);
    });
  });

  describe("module contract", () => {
    it("has no fetch or LLM imports in the public entrypoint", () => {
      const fs = require("fs");
      const path = require("path");
      const indexSource = fs.readFileSync(
        path.join(
          process.cwd(),
          "src/lib/workflows/new-seller/listing/index.ts",
        ),
        "utf8",
      );
      expect(indexSource).not.toMatch(/fetch\s*\(/);
      expect(indexSource).not.toMatch(/openai|anthropic|ollama/i);
    });
  });
});
