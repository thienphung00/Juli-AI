import { describe, expect, it } from "vitest";
import { fillRequest, senderMatches } from "../src/background/fill";
import { fillActive, PILOT_SHOP_IDS } from "../src/config";
import { GatewayClient, type TokenInfo } from "../src/ingest/client";
import { CODE, ITEM, rawRequest } from "./fill-helpers";

const PILOT = PILOT_SHOP_IDS[0]!;
const token = (shop_id: string): TokenInfo => ({
  token: "jci_x",
  token_id: "t1",
  shop_id,
  platform: "shopee",
  expires_at: "2027-01-10T00:00:00Z",
  rotate_after: "2026-11-11T00:00:00Z",
});

class MemoryStorage {
  constructor(public data: Record<string, unknown> = {}) {}
  async get(keys?: string | string[] | null) {
    const list = keys == null ? Object.keys(this.data) : Array.isArray(keys) ? keys : [keys];
    return Object.fromEntries(list.filter((k) => this.data[k] != null).map((k) => [k, this.data[k]]));
  }
  async set(items: Record<string, unknown>) {
    Object.assign(this.data, items);
  }
}

function setup(shop: string | null, answer: () => Response | Promise<Response>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const client = new GatewayClient(async (url, init) => {
    calls.push({ url, init });
    return answer();
  }, "https://api.example");
  const storage = new MemoryStorage(shop ? { token: token(shop) } : {});
  return { deps: { storage, client }, calls };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("the gate", () => {
  it("is on only for an explicit pilot shop", () => {
    expect(fillActive(PILOT)).toBe(true);
    expect(fillActive("some-other-shop")).toBe(false);
    expect(fillActive(undefined)).toBe(false);
    expect(fillActive("")).toBe(false);
  });

  it("is not opened by the readers' wildcard", () => {
    const ids = PILOT_SHOP_IDS as string[];
    ids.push("*");
    try {
      expect(fillActive("some-other-shop")).toBe(false);
    } finally {
      ids.pop();
    }
  });
});

describe("fillRequest", () => {
  it("stays inactive and asks Juli nothing without a token or on a shop outside the pilot", async () => {
    const none = setup(null, () => json(rawRequest()));
    expect(await fillRequest(none.deps, CODE, ITEM)).toEqual({ ok: false, reason: "inactive" });
    expect(none.calls).toEqual([]);
    const other = setup("not-the-pilot-shop", () => json(rawRequest()));
    expect(await fillRequest(other.deps, CODE, ITEM)).toEqual({ ok: false, reason: "inactive" });
    expect(other.calls).toEqual([]);
  });

  it("asks for the card with the token, by GET, and returns the validated request", async () => {
    const s = setup(PILOT, () => json(rawRequest()));
    const reply = await fillRequest(s.deps, CODE, ITEM);
    expect(reply.ok).toBe(true);
    expect(s.calls).toHaveLength(1);
    expect(s.calls[0]!.url).toBe(`https://api.example/v1/ingest/fill/${CODE}`);
    expect(s.calls[0]!.init?.method).toBe("GET");
    expect((s.calls[0]!.init?.headers as Record<string, string>).Authorization).toBe("Bearer jci_x");
    expect(s.calls[0]!.init?.credentials).toBe("omit");
    if (reply.ok) expect(reply.value.fields[0]?.value).toBe("Tên mới của sản phẩm mẫu");
  });

  it.each([
    [404, "fill_disabled", "disabled"],
    [404, "fill_unknown_card", "not_found"],
    [409, "fill_not_approved", "not_approved"],
    [422, "fill_not_supported", "unsupported"],
    [401, "invalid_token", "unpaired"],
    [500, "boom", "error"],
  ])("maps Juli's %s %s to %s", async (status, code, reason) => {
    const s = setup(PILOT, () => json({ detail: { code } }, status));
    expect(await fillRequest(s.deps, CODE, ITEM)).toEqual({ ok: false, reason });
  });

  it("refuses a malformed answer, a card of another item and a network failure", async () => {
    expect(await fillRequest(setup(PILOT, () => json({ nonsense: true })).deps, CODE, ITEM)).toEqual({ ok: false, reason: "error" });
    expect(await fillRequest(setup(PILOT, () => json(rawRequest({ item_id: "2002" }))).deps, CODE, ITEM)).toEqual({
      ok: false,
      reason: "wrong_item",
    });
    const down = setup(PILOT, () => {
      throw new TypeError("network");
    });
    expect(await fillRequest(down.deps, CODE, ITEM)).toEqual({ ok: false, reason: "error" });
  });
});

describe("senderMatches", () => {
  it("serves only the edit page of that item carrying that card's code", () => {
    const url = `https://banhang.shopee.vn/portal/product/${ITEM}#juli-fill=${CODE}`;
    expect(senderMatches(url, CODE, ITEM)).toBe(true);
    expect(senderMatches(url, CODE, "2002")).toBe(false);
    expect(senderMatches(url, "JC-2611-0008", ITEM)).toBe(false);
    expect(senderMatches(`https://banhang.shopee.vn/portal/product/list/all#juli-fill=${CODE}`, CODE, ITEM)).toBe(false);
    expect(senderMatches(`https://banhang.shopee.vn/portal/product/${ITEM}`, CODE, ITEM)).toBe(false);
    expect(senderMatches(undefined, CODE, ITEM)).toBe(false);
    expect(senderMatches("not a url", CODE, ITEM)).toBe(false);
    expect(senderMatches(url, "../../x", ITEM)).toBe(false);
  });
});
