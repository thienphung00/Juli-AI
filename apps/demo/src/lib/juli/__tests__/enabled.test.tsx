import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShopReportState } from "../../shop-report/shop-report-context";
import { fetchJuliEnabled, resetJuliEnabledCache, useJuliEnabled } from "../enabled";

const ready = (shopId: string): ShopReportState =>
  ({ status: "loading", token: "tok", shop: { id: shopId, name: "Shop mẫu" } }) as ShopReportState;

const respond = (status: number, body: unknown = {}) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

describe("useJuliEnabled", () => {
  beforeEach(() => resetJuliEnabledCache());

  it("{enabled:true} -> true, sent with the bearer and X-Shop-Id", async () => {
    const fetchImpl = respond(200, { enabled: true });
    const { result } = renderHook(() => useJuliEnabled(ready("s1"), fetchImpl));
    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current).toBe(true));
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0]!;
    expect(url).toBe("/v1/demo/juli/enabled");
    expect(init.headers).toMatchObject({ Authorization: "Bearer tok", "X-Shop-Id": "s1" });
  });

  it.each([
    ["{enabled:false}", respond(200, { enabled: false })],
    ["403", respond(403)],
    ["404", respond(404)],
    ["a bad body", respond(200, { enabled: "yes" })],
    ["a network error", vi.fn(async () => { throw new TypeError("offline"); }) as unknown as typeof fetch],
  ])("%s -> hidden, asked once, never retried", async (_name, fetchImpl) => {
    const { result, rerender } = renderHook(() => useJuliEnabled(ready("s2"), fetchImpl));
    await waitFor(() => expect(result.current).toBe(false));
    rerender();
    rerender();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("one fetch per shop: a second shop asks again, the first is cached", async () => {
    const fetchImpl = respond(200, { enabled: true });
    expect(await fetchJuliEnabled("t", "a", fetchImpl)).toBe(true);
    expect(await fetchJuliEnabled("t", "a", fetchImpl)).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await fetchJuliEnabled("t", "b", fetchImpl);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("no shop -> false without a request", () => {
    const fetchImpl = respond(200, { enabled: true });
    const { result } = renderHook(() => useJuliEnabled({ status: "anonymous", envelope: null } as ShopReportState, fetchImpl));
    expect(result.current).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
