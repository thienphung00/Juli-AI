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
      ["/v1/demo/shopee/recommendations/c1/approve", { inputs: { a: 1 }, note: null }],
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
});
