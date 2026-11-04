import { describe, expect, it, vi } from "vitest";

import { DEMO_RECO_BASE, createRecoApi, opsRecoBase } from "../client";

function stub(body: unknown = {}, status = 200) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch & ReturnType<typeof vi.fn>;
}

describe("recommendation client", () => {
  it("seller: bearer + X-Shop-Id, what-if unwraps the card", async () => {
    const f = stub({ card: { id: "c1" } });
    const api = createRecoApi({ base: DEMO_RECO_BASE, token: "t", shopId: "s1", fetchImpl: f });
    expect((await api.whatif("c1", { value: 1000 })).id).toBe("c1");
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/demo/shopee/recommendations/c1/whatif");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "s1" });
    expect(JSON.parse(init.body as string)).toEqual({ inputs: { value: 1000 } });
  });

  it("maps the decisions to the bodies the backend expects", async () => {
    const f = stub();
    const api = createRecoApi({ base: DEMO_RECO_BASE, token: "t", shopId: "s1", fetchImpl: f });
    await api.approve("c1", { inputs: { a: 1 } });
    await api.requestChange("c1", "note");
    await api.dismiss("c1", { reasonCode: "later" });
    await api.executed("c1", { voucherId: "v9" });
    const bodies = f.mock.calls.map((c) => [c[0], JSON.parse((c[1] as RequestInit).body as string)]);
    expect(bodies).toEqual([
      ["/v1/demo/shopee/recommendations/c1/approve", { inputs: { a: 1 }, note: null, chosen_version: 1, acknowledge_breaches: false }],
      ["/v1/demo/shopee/recommendations/c1/request-change", { note: "note" }],
      ["/v1/demo/shopee/recommendations/c1/dismiss", { reason_code: "later", note: null }],
      ["/v1/demo/shopee/recommendations/c1/executed", { executed_at: null, voucher_id: "v9", evidence_ref: null }],
    ]);
  });

  it("ops: shop in the path, no X-Shop-Id, list filters as query", async () => {
    const f = stub({ cards: [] });
    const api = createRecoApi({ base: opsRecoBase("abc"), token: "t", fetchImpl: f });
    await api.list({ status: "draft", xepTheo: "bien" });
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/ops/shops/abc/shopee/recommendations?status=draft&xep_theo=bien");
    expect((init.headers as Record<string, string>)["X-Shop-Id"]).toBeUndefined();
  });

  it("errors carry the backend code and message", async () => {
    const api = createRecoApi({ base: DEMO_RECO_BASE, token: "t", fetchImpl: stub({ detail: { code: "reco_floor_breach", message: "under floor" } }, 422) });
    await expect(api.approve("c1", {})).rejects.toMatchObject({ status: 422, code: "reco_floor_breach", message: "under floor" });
  });

  it("P91: what-if names the version; approve carries chosen_version and acknowledge_breaches", async () => {
    const f = stub({ card: { id: "c1" } });
    const api = createRecoApi({ base: DEMO_RECO_BASE, token: "t", shopId: "s1", fetchImpl: f });
    await api.whatif("c1", { value: 1000 }, 2);
    await api.approve("c1", { chosenVersion: 3, acknowledgeBreaches: true });
    const bodies = f.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string));
    expect(bodies[0]).toEqual({ inputs: { value: 1000 }, version: 2 });
    expect(bodies[1]).toEqual({ inputs: null, note: null, chosen_version: 3, acknowledge_breaches: true });
  });

  it("P91: list by product with the whole queue", async () => {
    const f = stub({ cards: [] });
    const api = createRecoApi({ base: DEMO_RECO_BASE, token: "t", shopId: "s1", fetchImpl: f });
    await api.list({ productId: "GT-A", queue: "all" });
    expect((f.mock.calls[0] as [string])[0]).toBe("/v1/demo/shopee/recommendations?product_id=GT-A&queue=all");
  });

  it("P91: compare, manual and the card by code go to the routes of the backend", async () => {
    const f = stub({ variants: [] });
    const api = createRecoApi({ base: opsRecoBase("abc"), token: "t", fetchImpl: f });
    const v = { change_kind: "combo_multi", items: ["a", "b"], extra: {}, inputs: {} };
    await api.compare([v, v], "2026-11-02");
    await api.createManual({ variants: [v], chosen: 0, primary: true, acknowledgeBreaches: true });
    await api.byCode("JC-2611-0007-V2");
    const calls = f.mock.calls.map((c) => [(c[1] as RequestInit).method, c[0], (c[1] as RequestInit).body ? JSON.parse((c[1] as RequestInit).body as string) : null]);
    expect(calls).toEqual([
      ["POST", "/v1/ops/shops/abc/shopee/recommendations/compare", { variants: [v, v], as_of: "2026-11-02" }],
      ["POST", "/v1/ops/shops/abc/shopee/recommendations/manual", { variants: [v], chosen: 0, primary: true, acknowledge_breaches: true }],
      ["GET", "/v1/ops/shops/abc/shopee/recommendations/code/JC-2611-0007-V2", null],
    ]);
  });

  it("P91: a 422 that needs a yes keeps its breaches", async () => {
    const breaches = [{ type: "floor", sku: "S1", floor: 100, min_unit_price: 90 }];
    const api = createRecoApi({ base: DEMO_RECO_BASE, token: "t", fetchImpl: stub({ detail: { code: "reco_breach_not_acknowledged", message: "acknowledge it", breaches } }, 422) });
    await expect(api.createManual({ variants: [], chosen: 0, primary: false, acknowledgeBreaches: false })).rejects.toMatchObject({ status: 422, code: "reco_breach_not_acknowledged", detail: { breaches } });
  });
});
