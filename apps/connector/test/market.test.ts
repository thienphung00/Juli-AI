// SYNTHETIC fixture of the recon-guessed shape of the public search answer
// (docs/integrations/shopee/market-search-recon.md): not a real capture.
import { describe, expect, it } from "vitest";
import { isMarketMessage } from "../src/content/messages";
import { MARKET_CHANNEL, MARKET_ORIGIN, marketActive, PILOT_SHOP_IDS } from "../src/config";
import { ingestBody } from "../src/ingest/client";
import {
  classifyAnswer,
  mapMarketSearch,
  marketBlockedPath,
  pickKeywords,
  sameKeyword,
  searchCall,
  searchPageUrl,
  trimSearchBody,
} from "../src/shopee/market";
import fixture from "./fixtures/market/search_items.json";

const NOW = Date.UTC(2026, 10, 5, 3, 0, 0);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const clone = (): any => JSON.parse(JSON.stringify(fixture));

describe("mapMarketSearch", () => {
  it("maps page-1 cards to rows with true positions, VND and the ad flag", () => {
    const post = mapMarketSearch("găng tay cao su", fixture, NOW);
    expect(post.drift).toBeNull();
    expect(post).toMatchObject({ dataset: "market_search", date: "2026-11-05", orderType: null, granularity: "period" });
    expect(post.rows).toHaveLength(3);
    expect(post.rows[0]).toEqual({
      keyword: "găng tay cao su",
      sort: "relevancy",
      page: 1,
      pos: 1,
      is_ad: false,
      item_id: "1000001",
      title: "Găng tay cao su loại 1",
      price: 130000,
      shop_id: "555001",
      shop_title: "Shop mẫu 1",
      price_min: 129000,
      price_max: 149000,
      price_before_discount: 159000,
      discount_pct: 18.2,
      rating: 4.87,
      sold_monthly: 95,
      sold_lifetime: 1201,
      sold_text: "Đã bán 95/tháng",
      image_id: "vn-11134207-synthetic-1",
    });
    expect(post.rows[2]).toMatchObject({ pos: 3, is_ad: true });
    // no range when min == max (here 0 / 0 is not a range) and sold falls back to `sold`
    expect(post.rows[1]).not.toHaveProperty("price_min");
    expect(post.rows[1]).toMatchObject({ sold_monthly: 82 });
    // nothing outside the contract, never a string in extra
    expect(JSON.stringify(post.rows)).not.toContain("user_secret");
    expect(post.rows.every((r) => !("extra" in r))).toBe(true);
  });

  it("builds the ingest body the gateway expects", () => {
    const body = ingestBody(mapMarketSearch("k", fixture, NOW), "0.3.5", NOW);
    expect(body.period).toEqual({ start: "2026-11-05", end: "2026-11-05", granularity: "period" });
    expect(body.order_type).toBeNull();
  });

  it("an empty list is a real empty result: no rows, no drift", () => {
    const post = mapMarketSearch("k", { error: null, items: [] }, NOW);
    expect(post.rows).toEqual([]);
    expect(post.drift).toBeNull();
  });

  it("no card list is drift (items missing)", () => {
    const post = mapMarketSearch("k", { error: null, other: 1 }, NOW);
    expect(post.drift).toEqual({ unexpected: [], missing: ["items"] });
    expect(post.rows).toEqual([]);
  });

  it("a card without item id, name or price is drift and posts nothing", () => {
    const body = clone();
    delete body.items[1].item_basic.itemid;
    delete body.items[0].item_basic.name;
    delete body.items[2].item_basic.price;
    delete body.items[2].item_basic.price_min;
    const post = mapMarketSearch("k", body, NOW);
    expect(post.drift?.missing.sort()).toEqual(["items[].itemid", "items[].name", "items[].price"]);
    expect(post.rows).toEqual([]);
  });

  it("a wrong price scale is drift (too large and too small)", () => {
    const big = clone();
    for (const it of big.items) it.item_basic.price = it.item_basic.price * 10_000;
    expect(mapMarketSearch("k", big, NOW).drift?.unexpected).toEqual(["market:price_scale"]);
    const small = clone();
    for (const it of small.items) it.item_basic.price = 129000; // sent as plain VND: 1 d after the divisor
    expect(mapMarketSearch("k", small, NOW).drift?.unexpected).toEqual(["market:price_scale"]);
  });
});

describe("trimSearchBody", () => {
  it("keeps only the public card fields", () => {
    const trimmed = JSON.stringify(trimSearchBody(fixture));
    expect(trimmed).not.toContain("user_secret");
    expect(trimmed).not.toContain("extra_tracking");
    expect(trimmed).toContain("1000001");
    // the trimmed answer maps to the same rows
    expect(mapMarketSearch("k", trimSearchBody(fixture), NOW).rows).toEqual(mapMarketSearch("k", fixture, NOW).rows);
  });
});

describe("pickKeywords", () => {
  const plan = {
    enabled: true,
    max_per_product: 3,
    products: [
      { item_id: "1", keywords: ["a one", "b two", "c three", "d four"] },
      { item_id: "2", keywords: ["B Two", "e five"] },
    ],
    due_keywords: ["a one", "b two", "c three", "e five", "d four"],
  };
  it("takes 1-3 per product, de-duplicates across products, honours the server's due list", () => {
    expect(pickKeywords(plan, {}, "2026-11-05")).toEqual(["a one", "b two", "c three", "e five"]);
    expect(pickKeywords({ ...plan, due_keywords: ["e five"] }, {}, "2026-11-05")).toEqual(["e five"]);
  });
  it("never reads a keyword twice within 6 days on this browser", () => {
    const last = { "a one": "2026-11-01", "b two": "2026-10-29" };
    expect(pickKeywords(plan, last, "2026-11-05")).toEqual(["b two", "c three", "e five"]);
  });
  it("disabled -> nothing; capped at 12", () => {
    expect(pickKeywords({ ...plan, enabled: false }, {}, "2026-11-05")).toEqual([]);
    const many = { enabled: true, products: Array.from({ length: 10 }, (_, i) => ({ keywords: [`k${i}a`, `k${i}b`, `k${i}c`] })) };
    expect(pickKeywords(many, {}, "2026-11-05")).toHaveLength(12);
  });
});

describe("page helpers", () => {
  it("recognises only the page-1 search call", () => {
    expect(searchCall("https://shopee.vn/api/v4/search/search_items?by=relevancy&keyword=g%C4%83ng%20tay&limit=60&newest=0")).toEqual({
      keyword: "găng tay",
    });
    expect(searchCall("https://shopee.vn/api/v4/search/search_items?keyword=x&newest=60")).toBeNull();
    expect(searchCall("https://shopee.vn/api/v4/recommend/recommend?keyword=x")).toBeNull();
    expect(searchCall("https://evil.example/api/v4/search/search_items?keyword=x")).toBeNull();
  });
  it("opens only the public search page", () => {
    expect(searchPageUrl("găng tay")).toBe("https://shopee.vn/search?keyword=g%C4%83ng%20tay");
    expect(sameKeyword(" Găng Tay ", "găng tay")).toBe(true);
  });
  it("walls and answers", () => {
    expect(marketBlockedPath("/verify/traffic")).toBe("captcha");
    expect(marketBlockedPath("/buyer/login")).toBe("login");
    expect(marketBlockedPath("/search")).toBeNull();
    expect(classifyAnswer(403, null)).toBe("captcha");
    expect(classifyAnswer(200, { error: 90309999 })).toBe("captcha");
    expect(classifyAnswer(200, { error: 5 })).toBe("error");
    expect(classifyAnswer(200, { error: null, items: [] })).toBe("ok");
    expect(classifyAnswer(500, null)).toBe("error");
  });
});

describe("gating and messages", () => {
  it("ORY only: the explicit pilot id counts, the wildcard and others do not", () => {
    expect(marketActive(PILOT_SHOP_IDS[0])).toBe(true);
    expect(marketActive("other-shop")).toBe(false);
    expect(marketActive(undefined)).toBe(false);
  });
  it("the relay accepts only its own window, the shopee.vn origin, the market channel and kind", () => {
    const self = {};
    const ok = { source: self, origin: MARKET_ORIGIN, data: { channel: MARKET_CHANNEL, kind: "market-answer" } };
    expect(isMarketMessage(ok, self, MARKET_ORIGIN, MARKET_CHANNEL)).toBe(true);
    expect(isMarketMessage({ ...ok, origin: "https://banhang.shopee.vn" }, self, MARKET_ORIGIN, MARKET_CHANNEL)).toBe(false);
    expect(isMarketMessage({ ...ok, source: {} }, self, MARKET_ORIGIN, MARKET_CHANNEL)).toBe(false);
    expect(isMarketMessage({ ...ok, data: { channel: "juli-connector/v1", kind: "market-answer" } }, self, MARKET_ORIGIN, MARKET_CHANNEL)).toBe(false);
    expect(isMarketMessage({ ...ok, data: { channel: MARKET_CHANNEL, kind: "capture" } }, self, MARKET_ORIGIN, MARKET_CHANNEL)).toBe(false);
  });
});
