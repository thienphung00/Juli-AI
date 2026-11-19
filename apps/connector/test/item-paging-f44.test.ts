import { describe, expect, it } from "vitest";
import { L1_SOURCES } from "../src/platforms/shopee/map";
import { Pacer, runDay, type DayRequest } from "../src/platforms/shopee/runner";
import { buildBackfillDayPlan, buildSyncPlan, ITEM_SOURCE_PAGES } from "../src/platforms/shopee/sync";

const NOW = Date.UTC(2026, 10, 19, 3, 0, 0);

function item(id: number) {
  return { item_id: id, name: `Item ${id}`, sales: 1000, orders: 1 };
}
const listOf = (n: number, from = 1) => ({ code: 0, msg: "ok", result: { item: Array.from({ length: n }, (_, i) => item(from + i)) } });

describe("F4.4 item_by_source covers every product (paged per L1 source)", () => {
  it("plans every page of every L1 source, in order, in the daily and the backfill plan", () => {
    for (const plan of [buildSyncPlan(NOW, new Set(), true), buildBackfillDayPlan("2026-11-10", NOW, new Set(), true)]) {
      const reqs = plan.filter((p) => p.dataset === "item_by_source");
      expect(reqs).toHaveLength(L1_SOURCES.length * ITEM_SOURCE_PAGES);
      for (const source of L1_SOURCES) {
        const pages = reqs.filter((p) => p.params.l1_source === source).map((p) => p.params.page_num);
        expect(pages).toEqual(Array.from({ length: ITEM_SOURCE_PAGES }, (_, i) => String(i + 1)));
      }
      expect(reqs.every((p) => p.page?.pageSize === 10)).toBe(true);
    }
  });

  it("keeps shop-level reads ahead of the item pages (lowest priority)", () => {
    const plan = buildBackfillDayPlan("2026-11-10", NOW, new Set(), true);
    const firstItem = plan.findIndex((p) => p.dataset === "item_performance" || p.dataset === "item_by_source");
    const lastShop = plan.map((p) => p.dataset).lastIndexOf("shop_traffic");
    expect(lastShop).toBeLessThan(firstItem);
  });

  it("sends the next page only after a full page and stops a source at its short page", async () => {
    const plan = buildBackfillDayPlan("2026-11-10", NOW, new Set(["traffic_overview", "shop_traffic", "item_performance", "product_overview"] as const), true);
    const requests: DayRequest[] = plan.map((p) => {
      const url = `https://banhang.shopee.vn${p.path}?${new URLSearchParams(p.params)}`;
      return { dataset: p.dataset, url, publicUrl: url, ...(p.page ? { page: p.page } : {}) };
    });
    // product_card has 25 products (10 + 10 + 5), every other source has 3.
    const seen: string[] = [];
    const fetchImpl = async (url: string) => {
      const q = new URL(url).searchParams;
      const source = q.get("l1_source")!;
      const page = Number(q.get("page_num"));
      seen.push(`${source}:${page}`);
      const body = source === "psd_label_product_card" ? listOf(page < 3 ? 10 : 5) : listOf(3);
      return { status: 200, text: async () => JSON.stringify(body) };
    };
    let t = 0;
    const pacer = new Pacer({ sleep: async (ms) => void (t += ms), now: () => t, random: () => 0 });
    const results = await runDay(requests, pacer, fetchImpl, () => t);
    expect(seen.filter((s) => s.startsWith("psd_label_product_card"))).toEqual([
      "psd_label_product_card:1",
      "psd_label_product_card:2",
      "psd_label_product_card:3",
    ]);
    expect(results).toHaveLength(3 + 4);
  });

  it("an exactly full last page asks for one more, then stops on the empty page", async () => {
    const plan = buildSyncPlan(NOW, new Set(["traffic_overview", "shop_traffic", "item_performance", "product_overview"] as const), true).filter(
      (p) => p.params.l1_source === "psd_label_seller_live",
    );
    const requests: DayRequest[] = plan.map((p) => ({ dataset: p.dataset, url: `u?page=${p.params.page_num}`, publicUrl: "u", page: p.page! }));
    const sentPages: string[] = [];
    const fetchImpl = async (url: string) => {
      const page = Number(url.split("=")[1]);
      sentPages.push(String(page));
      return { status: 200, text: async () => JSON.stringify(listOf(page === 1 ? 10 : 0)) };
    };
    let t = 0;
    const pacer = new Pacer({ sleep: async (ms) => void (t += ms), now: () => t, random: () => 0 });
    await runDay(requests, pacer, fetchImpl, () => t);
    expect(sentPages).toEqual(["1", "2"]);
  });
});

import { trafficDaysWithinCap } from "../src/platforms/shopee/reader";

describe("F4.4 item_traffic_sources reads whole days", () => {
  it("takes a day only when all its items fit the job's request cap", () => {
    const days = ["2026-11-18", "2026-11-17", "2026-11-16", "2026-11-15"];
    expect(trafficDaysWithinCap(days, 200, 600)).toEqual(days.slice(0, 3));
    expect(trafficDaysWithinCap(days, 250, 600)).toEqual(days.slice(0, 2));
    expect(trafficDaysWithinCap(days, 700, 600)).toEqual(days.slice(0, 1)); // first day always
    expect(trafficDaysWithinCap(days, 0, 600)).toEqual([]);
  });
});
