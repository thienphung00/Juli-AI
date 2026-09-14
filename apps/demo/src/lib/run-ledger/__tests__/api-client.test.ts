import { describe, expect, it, vi } from "vitest";

import { DEMO_RUNS_API_PATH, DemoRunsFetchError, fetchDemoRuns } from "../api-client";
import { buildRunListItem } from "./fixtures";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as Response;
}

describe("fetchDemoRuns", () => {
  it("requests exactly GET /v1/demo/runs — the polled read model, never the SSE event endpoint", async () => {
    const run = buildRunListItem({ id: "run-1" });
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ success: true, data: [run] }));

    await fetchDemoRuns({ fetchImpl: fetchImpl as unknown as typeof fetch });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(DEMO_RUNS_API_PATH);
    expect(url).not.toContain("/events");
    expect(init).toMatchObject({ cache: "no-store" });
  });

  it("resolves with the response's data array, unmodified", async () => {
    const runs = [buildRunListItem({ id: "run-1" }), buildRunListItem({ id: "run-2" })];
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ success: true, data: runs }));

    const result = await fetchDemoRuns({ fetchImpl: fetchImpl as unknown as typeof fetch });

    expect(result).toEqual(runs);
  });

  it("throws DemoRunsFetchError with the response status on a non-2xx response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, false, 500));

    await expect(
      fetchDemoRuns({ fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toThrow(DemoRunsFetchError);
  });
it("sends the bearer token and X-Shop-Id the backend's get_active_shop requires (#1909)", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ success: true, data: [] }));

    await fetchDemoRuns({
      token: "bearer-1",
      shopId: "shop-1",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [, init] = fetchImpl.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("Authorization")).toBe("Bearer bearer-1");
    expect(headers.get("X-Shop-Id")).toBe("shop-1");
  });

  it("sends no Authorization or X-Shop-Id header when called with no credentials", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ success: true, data: [] }));

    await fetchDemoRuns({ fetchImpl: fetchImpl as unknown as typeof fetch });

    const [, init] = fetchImpl.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("Authorization")).toBeNull();
    expect(headers.get("X-Shop-Id")).toBeNull();
  });
});
