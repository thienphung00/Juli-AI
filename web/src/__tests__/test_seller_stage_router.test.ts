/**
 * Issue #116 — Rules-based seller-stage router (P1-6)
 */
import { loadPersona } from "@/lib/mock-data/seller-personas";
import {
  classifySellerStage,
  STAGE_BOUNDARY_FIXTURES,
  AD_SPEND_GROWTH_MIN_VND,
  ORDER_COUNT_GROWTH_MIN,
  ORDER_COUNT_NEW_MAX,
  RETURN_RATE_LEAKAGE_MIN,
  SHOP_AGE_NEW_MAX_DAYS,
} from "@/lib/seller-stage-router";
import type { SellerStageInput } from "@/lib/seller-stage-router";

function profile(overrides: Partial<SellerStageInput> = {}): SellerStageInput {
  return {
    shop_age_days: 90,
    order_count_30d: 40,
    return_rate_30d: 0.06,
    ad_spend_30d_vnd: 3_000_000,
    ...overrides,
  };
}

describe("Issue #116: classifySellerStage", () => {
  describe("persona fixtures (#114)", () => {
    it("classifies new persona as new", () => {
      expect(classifySellerStage(loadPersona("new").profile)).toBe("new");
    });

    it("classifies leakage persona as leakage", () => {
      expect(classifySellerStage(loadPersona("leakage").profile)).toBe("leakage");
    });

    it("classifies growth persona as growth", () => {
      expect(classifySellerStage(loadPersona("growth").profile)).toBe("growth");
    });
  });

  describe("threshold documentation", () => {
    it("exports documented threshold constants", () => {
      expect(RETURN_RATE_LEAKAGE_MIN).toBe(0.1);
      expect(ORDER_COUNT_NEW_MAX).toBe(15);
      expect(SHOP_AGE_NEW_MAX_DAYS).toBe(45);
      expect(ORDER_COUNT_GROWTH_MIN).toBe(50);
      expect(AD_SPEND_GROWTH_MIN_VND).toBe(5_000_000);
    });
  });

  describe("determinism", () => {
    it("runs without network or database dependencies", () => {
      expect(classifySellerStage(loadPersona("new").profile)).toBe("new");
    });

    it("returns the same stage for repeated calls with identical input", () => {
      const input = loadPersona("growth").profile;
      const first = classifySellerStage(input);
      const second = classifySellerStage(input);

      expect(first).toBe(second);
      expect(first).toBe("growth");
    });
  });

  describe("golden boundary fixtures", () => {
    it.each(STAGE_BOUNDARY_FIXTURES)(
      "$id → $expectedStage ($note)",
      ({ profile: fixtureProfile, expectedStage }) => {
        expect(classifySellerStage(fixtureProfile)).toBe(expectedStage);
      },
    );
  });

  describe("edge cases at threshold boundaries", () => {
    it("routes low-volume sellers as new even when return rate is elevated", () => {
      expect(
        classifySellerStage(
          profile({
            order_count_30d: 10,
            return_rate_30d: 0.25,
          }),
        ),
      ).toBe("new");
    });

    it("routes established sellers with sub-growth volume to growth by default", () => {
      expect(
        classifySellerStage(
          profile({
            shop_age_days: 120,
            order_count_30d: 30,
            return_rate_30d: 0.06,
            ad_spend_30d_vnd: 2_000_000,
          }),
        ),
      ).toBe("growth");
    });
  });
});
