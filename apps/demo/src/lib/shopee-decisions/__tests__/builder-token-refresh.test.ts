import { beforeEach, describe, expect, it, vi } from "vitest";

import { createBuilderApi } from "../builder-api";

const mocks = vi.hoisted(() => ({ stored: null as { accessToken: string } | null, refresh: vi.fn() }));
vi.mock("../../supabase-auth", () => ({ readAuthSession: () => mocks.stored }));
vi.mock("../../auth-refresh", () => ({ refreshAuthSession: mocks.refresh }));

const ok = () => new Response(JSON.stringify({ versions: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
const unauthorized = () => new Response(JSON.stringify({ detail: "Invalid or expired credentials" }), { status: 401, headers: { "Content-Type": "application/json" } });

describe("the builder client keeps its token fresh", () => {
  beforeEach(() => {
    mocks.stored = null;
    mocks.refresh.mockReset();
  });

  it("retries a 401 with the stored (refreshed) token and keeps using it", async () => {
    mocks.stored = { accessToken: "new" };
    const seen: string[] = [];
    const fetchImpl = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const bearer = String((init?.headers as Record<string, string>)["Authorization"]);
      seen.push(bearer);
      return bearer === "Bearer new" ? ok() : unauthorized();
    });
    const api = createBuilderApi({ base: "/v1/demo/shopee/builder", token: "old", fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(api.evaluate([])).resolves.toBeTruthy();
    await api.compare([]);
    expect(seen).toEqual(["Bearer old", "Bearer new", "Bearer new"]);
    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it("refreshes when the stored token is the rejected one", async () => {
    mocks.stored = { accessToken: "old" };
    mocks.refresh.mockResolvedValue({ accessToken: "fresh" });
    const fetchImpl = vi.fn(async (_url: unknown, init?: RequestInit) => ((init?.headers as Record<string, string>)["Authorization"] === "Bearer fresh" ? ok() : unauthorized()));
    const api = createBuilderApi({ base: "/v1/demo/shopee/builder", token: "old", fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(api.evaluate([])).resolves.toBeTruthy();
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it("still fails with the 401 when nothing newer exists", async () => {
    mocks.stored = { accessToken: "old" };
    mocks.refresh.mockResolvedValue(null);
    const api = createBuilderApi({ base: "/v1/demo/shopee/builder", token: "old", fetchImpl: (async () => unauthorized()) as unknown as typeof fetch });
    await expect(api.evaluate([])).rejects.toMatchObject({ status: 401 });
  });
});
