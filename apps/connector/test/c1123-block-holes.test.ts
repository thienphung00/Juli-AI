// batch-1123-a Track C, 1(b): after a Phân tích bán hàng login / password block clears, the next
// plan (the re-read or the next daily run, both fetch the hole list) reads every missing day of
// the blocked datasets, oldest first, within the backfill room. Made-up data only.
import { describe, expect, it } from "vitest";
import { planJobs } from "../src/platforms/shopee/background/scheduler";
import { CATCHUP_DAYS_PER_JOB } from "../src/platforms/shopee/config";

const SHOP = "5b0c1d2e-3f40-4a51-8b62-7c83d94e0a15";
const NOW = Date.UTC(2026, 10, 23, 3, 0, 0); // 2026-11-23 10:00 GMT+7
const base = { shopId: SHOP, nowMs: NOW, stopped: new Set<never>(), adsDone: [] as string[] };
// item_traffic_sources was blocked since 17/11, shop_overview since 21/11.
const holes = {
  item_traffic_sources: ["2026-11-22", "2026-11-17", "2026-11-19", "2026-11-18", "2026-11-21", "2026-11-20"],
  shop_overview: ["2026-11-21", "2026-11-22"],
};

describe("C1123 1(b): blocked days are read again once the block clears", () => {
  it("item traffic: the recent days first, then the oldest holes, capped by the room and per job", () => {
    const jobs = planJobs({ ...base, readers: ["item_traffic"], holes, holeRoom: 150, itemCount: 40 });
    const days = jobs.filter((j) => j.id === "item_traffic").map((j) => j.days);
    expect(days[0]).toEqual(["2026-11-22", "2026-11-21", "2026-11-20", "2026-11-19"]);
    expect(days[1]).toEqual(["2026-11-17", "2026-11-18"].slice(0, CATCHUP_DAYS_PER_JOB.item_traffic));
    // no room left: only the recent days, the oldest holes wait for the next run
    const tight = planJobs({ ...base, readers: ["item_traffic"], holes, holeRoom: 39, itemCount: 40 });
    expect(tight.filter((j) => j.id === "item_traffic").map((j) => j.days)).toEqual([["2026-11-22", "2026-11-21", "2026-11-20", "2026-11-19"]]);
  });

  it("shop totals: the blocked days are inside its own refresh window", () => {
    const jobs = planJobs({ ...base, readers: ["shop_totals"], holes, holeRoom: 150, totalsBackfilled: true });
    const all = jobs.filter((j) => j.id === "shop_totals").flatMap((j) => j.days ?? []);
    expect(all).toEqual(expect.arrayContaining(["2026-11-21", "2026-11-22"]));
  });

  it("the next run plans the next oldest holes (an older one found later comes first)", () => {
    const later = { ...holes, item_traffic_sources: holes.item_traffic_sources.filter((d) => d !== "2026-11-17" && d !== "2026-11-18") };
    const jobs = planJobs({
      ...base,
      readers: ["item_traffic"],
      holes: { ...later, item_traffic_sources: [...later.item_traffic_sources, "2026-11-10"] },
      holeRoom: 150,
      itemCount: 40,
      trafficDone: ["2026-11-22", "2026-11-21", "2026-11-20", "2026-11-19"],
    });
    expect(jobs.filter((j) => j.id === "item_traffic").map((j) => j.days)).toEqual([["2026-11-10", "2026-11-19"]]); // oldest first, two a job
  });
});
