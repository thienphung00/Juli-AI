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

    await fetchDemoRuns(fetchImpl as unknown as typeof fetch);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(DEMO_RUNS_API_PATH);
    expect(url).not.toContain("/events");
    expect(init).toMatchObject({ cache: "no-store" });
  });

  it("resolves with the response's data array, unmodified", async () => {
    const runs = [buildRunListItem({ id: "run-1" }), buildRunListItem({ id: "run-2" })];
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ success: true, data: runs }));

    const result = await fetchDemoRuns(fetchImpl as unknown as typeof fetch);

    expect(result).toEqual(runs);
  });

  it("throws DemoRunsFetchError with the response status on a non-2xx response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, false, 500));

    await expect(fetchDemoRuns(fetchImpl as unknown as typeof fetch)).rejects.toThrow(
      DemoRunsFetchError,
    );
  });
});
