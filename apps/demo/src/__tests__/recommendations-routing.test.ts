import { describe, expect, it, vi } from "vitest";

import {
  buildDecisionsHighlightHref,
  buildRecommendationDetailHref,
  recommendationFixtures,
} from "../lib/recommendations";
import {
  DEMO_DECISIONS_API_PATH,
  DemoRecommendationsFetchError,
  fetchRecommendations,
} from "../lib/recommendations-api-client";

describe("recommendations routing helpers", () => {
  it("builds detail and highlight hrefs for list ↔ detail navigation", () => {
    expect(buildRecommendationDetailHref("create_hero_product_1")).toBe(
      "/decisions/recommendations/create_hero_product_1",
    );
    expect(buildDecisionsHighlightHref("optimize_product_2")).toBe(
      "/decisions?highlight=optimize_product_2",
    );
  });

  it("targets the real Decisions read route (#1320) — /v1/demo/recommendations never existed", () => {
    expect(DEMO_DECISIONS_API_PATH).toBe("/v1/demo/decisions");
  });

  it("resolves recommendations from a successful signed-in fetch against the real route constant", async () => {
    const served = [recommendationFixtures[0]];
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ recommendations: served }),
    } as Response);

    await expect(fetchRecommendations(fetchImpl)).resolves.toEqual(served);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [calledUrl] = fetchImpl.mock.calls[0] as [string];
    expect(calledUrl).toBe(DEMO_DECISIONS_API_PATH);
  });

  it("surfaces a failed fetch as an honest error state — never recommendationFixtures (#1320)", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("network"));

    // The historical defect: a rejected fetch used to silently resolve to
    // `recommendationFixtures`, making a dead backend look healthy. It must
    // reject instead, so a caller can render an honest error state.
    await expect(fetchRecommendations(fetchImpl)).rejects.toThrow("network");
  });

  it("surfaces a non-OK response as DemoRecommendationsFetchError, never fixtures", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({}),
    } as Response);

    await expect(fetchRecommendations(fetchImpl)).rejects.toBeInstanceOf(
      DemoRecommendationsFetchError,
    );
  });

  it("surfaces a malformed 200 payload as a failure rather than the fixture set", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    } as Response);

    await expect(fetchRecommendations(fetchImpl)).rejects.toBeInstanceOf(
      DemoRecommendationsFetchError,
    );
  });
});
