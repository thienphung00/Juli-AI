import { GOLDEN_DEMO_DECISION_EXECUTABLE } from "@juli/contracts";
import { describe, expect, it, vi } from "vitest";

import {
  buildDecisionsHighlightHref,
  buildRecommendationDetailHref,
} from "../lib/recommendations";
import {
  DEMO_DECISIONS_API_PATH,
  DemoDecisionApproveError,
  DemoRecommendationsFetchError,
  approveDemoDecision,
  fetchRecommendations,
} from "../lib/recommendations-api-client";

const AUTH = { token: "bearer-token-1", shopId: "shop-1" };

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

  it("resolves the server's own decision envelope (data, not recommendations) and sends bearer + X-Shop-Id (#1909)", async () => {
    const served = [GOLDEN_DEMO_DECISION_EXECUTABLE];
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: served, error: null }),
    } as Response);

    await expect(
      fetchRecommendations({ ...AUTH, fetchImpl }),
    ).resolves.toEqual(served);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toBe(DEMO_DECISIONS_API_PATH);
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer bearer-token-1");
    expect(headers.get("X-Shop-Id")).toBe("shop-1");
  });

  it("surfaces a failed fetch as an honest error state — never recommendationFixtures (#1320)", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("network"));

    // The historical defect: a rejected fetch used to silently resolve to
    // `recommendationFixtures`, making a dead backend look healthy. It must
    // reject instead, so a caller can render an honest error state.
    await expect(fetchRecommendations({ ...AUTH, fetchImpl })).rejects.toThrow(
      "network",
    );
  });

  it("surfaces a non-OK response as DemoRecommendationsFetchError, never fixtures", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({}),
    } as Response);

    await expect(
      fetchRecommendations({ ...AUTH, fetchImpl }),
    ).rejects.toBeInstanceOf(DemoRecommendationsFetchError);
  });

  it("surfaces a malformed 200 payload as a failure rather than the fixture set", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    } as Response);

    await expect(
      fetchRecommendations({ ...AUTH, fetchImpl }),
    ).rejects.toBeInstanceOf(DemoRecommendationsFetchError);
  });
});

describe("approveDemoDecision — approve-is-run-creation, from the browser (#1909)", () => {
  it("POSTs to /v1/demo/decisions/{id}/approve with bearer + X-Shop-Id and resolves the SERVER's run_id", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({
        success: true,
        data: {
          run_id: "3f65f4b2-8f2a-47f6-9c93-2a2d0a2f9b11",
          action_card_id: "00000000-0000-0000-0000-000000000001",
          product_id: "00000000-0000-0000-0000-000000000009",
          status: "queued",
          celery_task_id: "task-1",
        },
        error: null,
      }),
    } as Response);

    await expect(
      approveDemoDecision("00000000-0000-0000-0000-000000000001", {
        ...AUTH,
        fetchImpl,
      }),
    ).resolves.toEqual({ runId: "3f65f4b2-8f2a-47f6-9c93-2a2d0a2f9b11" });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toBe(
      "/v1/demo/decisions/00000000-0000-0000-0000-000000000001/approve",
    );
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer bearer-token-1");
    expect(headers.get("X-Shop-Id")).toBe("shop-1");
  });

  it.each([401, 404, 409])(
    "rejects a %s with DemoDecisionApproveError carrying the status — never a fabricated run id",
    async (status) => {
      const fetchImpl = vi.fn().mockResolvedValue({
        ok: false,
        status,
        json: async () => ({ detail: "nope" }),
      } as Response);

      const rejection = approveDemoDecision("card-1", { ...AUTH, fetchImpl });

      await expect(rejection).rejects.toBeInstanceOf(DemoDecisionApproveError);
      await expect(rejection).rejects.toMatchObject({ status });
    },
  );

  it("rejects a 202 whose body carries no run_id — a client-constructed id must never stand in", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ success: true, data: null, error: null }),
    } as Response);

    await expect(
      approveDemoDecision("card-1", { ...AUTH, fetchImpl }),
    ).rejects.toBeInstanceOf(DemoDecisionApproveError);
  });
});
