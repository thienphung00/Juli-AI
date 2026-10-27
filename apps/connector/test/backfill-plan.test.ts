import { describe, expect, it } from "vitest";
import { Pacer, runDay, type DayRequest } from "../src/shopee/runner";
import { backfillDatasets, buildBackfillDayPlan, waitBefore } from "../src/shopee/sync";
import { gmt7DateStart, lastFinishedDays, singleDay } from "../src/shopee/time";

const NOW = Date.UTC(2026, 9, 26, 3, 0, 0); // 2026-10-26 10:00 GMT+7
const OCT1 = 1790787600;

describe("backfill day plan", () => {
  it("asks for 30 finished days, one plan per day, in the recorded shapes", () => {
    const days = lastFinishedDays(NOW, 30);
    const plans = days.map((day) => buildBackfillDayPlan(day, NOW, new Set()));
    expect(plans).toHaveLength(30);
    for (const [index, plan] of plans.entries()) {
      const day = days[index]!;
      const start = gmt7DateStart(day);
      expect(plan.map((p) => p.dataset)).toEqual(["traffic_overview", "shop_traffic"]);
      const [overview, traffic] = plan;
      if (index === 0) {
        // yesterday: as "Hôm qua" sends it
        expect(overview!.params).toEqual({
          start_time: String(start),
          end_time: String(start + 86399),
          period: "yesterday",
          order_type: "confirmed",
        });
      } else {
        expect(overview!.params).toEqual({
          start_time: String(start),
          end_time: String(start + 86400),
          period: "day",
          order_type: "confirmed",
        });
      }
      expect(traffic!.params).toEqual({ period: "day", dt: day.replaceAll("-", "") });
      expect(traffic!.useTemplate).toBeUndefined();
      // Every planned call is one the passive mapper reads back as exactly that day.
      for (const request of plan) {
        expect(singleDay(new URLSearchParams(request.params), NOW)).toBe(day);
      }
    }
  });

  it("matches the recorded 2026-10-01 URL", () => {
    const [overview, traffic] = buildBackfillDayPlan("2026-10-01", NOW, new Set());
    expect(overview!.path).toBe("/api/mydata/v1/product/traffic/overview/");
    expect(new URLSearchParams(overview!.params).toString()).toBe(
      `start_time=${OCT1}&end_time=${OCT1 + 86400}&period=day&order_type=confirmed`,
    );
    expect(traffic!.path).toBe("/api/mydata/traffic/dashboard/overview/");
    expect(new URLSearchParams(traffic!.params).toString()).toBe("period=day&dt=20261001");
  });

  it("skips accepted / stopped datasets; item datasets only while their readers are active", () => {
    expect(buildBackfillDayPlan("2026-10-01", NOW, new Set(["traffic_overview"] as const)).map((p) => p.dataset)).toEqual([
      "shop_traffic",
    ]);
    expect(backfillDatasets()).toEqual(["traffic_overview", "shop_traffic"]);
    const withItems = buildBackfillDayPlan("2026-10-01", NOW, new Set(), true);
    expect(withItems.filter((p) => p.dataset === "item_performance")).toHaveLength(5);
    expect(withItems.filter((p) => p.dataset === "item_by_source")).toHaveLength(5);
    const item = withItems.find((p) => p.dataset === "item_performance")!;
    expect(item.params).toMatchObject({ period: "day", end_time: String(OCT1 + 86400), order_by: "confirmed_sales.desc" });
  });
});

describe("request pacing", () => {
  it("waits ≥ 2 s + jitter after the previous request, across plans", () => {
    expect(waitBefore(undefined, 1000)).toBe(0);
    expect(waitBefore(10_000, 10_000, () => 0)).toBe(2000);
    expect(waitBefore(10_000, 11_500, () => 0)).toBe(500);
    expect(waitBefore(10_000, 20_000, () => 0.999)).toBe(0);
    expect(waitBefore(10_000, 10_000, () => 0.999)).toBeLessThan(3500);
  });

  function fakeClock() {
    let now = 1_000_000;
    return {
      now: () => now,
      sleep: async (ms: number) => {
        now += ms;
      },
      advance: (ms: number) => {
        now += ms;
      },
    };
  }

  const requests = (n: number): DayRequest[] =>
    Array.from({ length: n }, (_, i) => ({
      dataset: i % 2 ? "shop_traffic" : "traffic_overview",
      url: `https://banhang.shopee.vn/r${i}?SPC_CDS=s`,
      publicUrl: `https://banhang.shopee.vn/r${i}`,
    }));

  it("sends a 30-day backfill with every request ≥ 2 s after the previous one", async () => {
    const clock = fakeClock();
    const pacer = new Pacer({ ...clock, random: Math.random });
    const sentAt: number[] = [];
    const fetchOk = async () => {
      sentAt.push(clock.now());
      clock.advance(300); // response time
      return { status: 200, text: async () => '{"code":0,"msg":"ok","result":{}}' };
    };
    for (let day = 0; day < 30; day += 1) {
      await pacer.serial(() => runDay(requests(2), pacer, fetchOk, clock.now));
    }
    expect(sentAt).toHaveLength(60);
    for (let i = 1; i < sentAt.length; i += 1) {
      expect(sentAt[i]! - sentAt[i - 1]!).toBeGreaterThanOrEqual(2000);
      expect(sentAt[i]! - sentAt[i - 1]!).toBeLessThan(3500 + 300);
    }
  });

  it("runs plans one at a time and reports without session params; stops at a non-data answer", async () => {
    const clock = fakeClock();
    const pacer = new Pacer({ ...clock, random: () => 0 });
    const urls: string[] = [];
    const answer10006 = async (url: string) => {
      urls.push(url);
      return { status: 200, text: async () => '{"code":10006,"msg":"err:invalid param, detail:unknown error"}' };
    };
    const results = await runDay(requests(2), pacer, answer10006, clock.now);
    expect(urls).toHaveLength(1); // the second call is not sent
    expect(results).toEqual([
      {
        dataset: "traffic_overview",
        url: "https://banhang.shopee.vn/r0",
        status: 200,
        body: { code: 10006, msg: "err:invalid param, detail:unknown error" },
        capturedAt: clock.now(),
      },
    ]);
    const login = await runDay(requests(1), pacer, async () => ({ status: 200, text: async () => "<html>" }), clock.now);
    expect(login[0]).toMatchObject({ status: 200, body: null });
    const offline = await runDay(
      requests(1),
      pacer,
      async () => {
        throw new TypeError("Failed to fetch");
      },
      clock.now,
    );
    expect(offline[0]).toMatchObject({ status: 0, body: null });

    const order: string[] = [];
    const slow = pacer.serial(async () => {
      order.push("a-start");
      await clock.sleep(10);
      order.push("a-end");
    });
    const fast = pacer.serial(async () => {
      order.push("b");
    });
    await Promise.all([slow, fast]);
    expect(order).toEqual(["a-start", "a-end", "b"]);
  });
});
