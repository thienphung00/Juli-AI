import {
  isActionableHostMatch,
  isSparseRecommendations,
  matchScorePercent,
} from "@/lib/recommendation-utils";
import type { RecommendationItem } from "@/lib/api-client";

const hostMatch = (overrides: Partial<RecommendationItem> = {}): RecommendationItem => ({
  id: "rec-1",
  recommendation_type: "host_product_match",
  message: "Match",
  cta: "Go",
  match_score: 0.82,
  ...overrides,
});

describe("recommendation-utils sparse graph", () => {
  it("treats empty list as sparse", () => {
    expect(isSparseRecommendations([])).toBe(true);
  });

  it("treats product_push-only feed as sparse", () => {
    expect(
      isSparseRecommendations([
        {
          id: "push-1",
          recommendation_type: "product_push",
          message: "Push",
          cta: "Pin",
        },
      ])
    ).toBe(true);
  });

  it("treats low-confidence host matches as sparse", () => {
    expect(
      isSparseRecommendations([
        hostMatch({ match_score: 0.35, confidence: "high" }),
      ])
    ).toBe(true);
    expect(
      isSparseRecommendations([hostMatch({ confidence: "low", match_score: 0.9 })])
    ).toBe(true);
    expect(isActionableHostMatch(hostMatch({ confidence: "low" }))).toBe(false);
  });

  it("is actionable when host_product_match meets score threshold", () => {
    const item = hostMatch({ match_score: 0.82 });
    expect(isActionableHostMatch(item)).toBe(true);
    expect(isSparseRecommendations([item])).toBe(false);
    expect(matchScorePercent(item)).toBe(82);
  });
});
