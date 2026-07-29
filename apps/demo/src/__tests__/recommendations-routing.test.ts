import { describe, expect, it, vi } from "vitest";

import {
  buildDecisionsHighlightHref,
  buildRecommendationDetailHref,
  fetchRecommendations,
  recommendationFixtures,
} from "../lib/recommendations";

describe("recommendations routing helpers", () => {
  it("builds detail and highlight hrefs for list ↔ detail navigation", () => {
    expect(buildRecommendationDetailHref("create_hero_product_1")).toBe(
      "/decisions/recommendations/create_hero_product_1",
    );
    expect(buildDecisionsHighlightHref("optimize_product_2")).toBe(
      "/decisions?highlight=optimize_product_2",
    );
  });

  it("falls back to fixtures when the Phase 2.10 read path is unavailable", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("network"));

    await expect(fetchRecommendations(fetchImpl)).resolves.toEqual(
      recommendationFixtures,
    );
  });
});
