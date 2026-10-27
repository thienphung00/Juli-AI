import { describe, expect, it } from "vitest";
import { mapCaptured } from "../src/shopee/map";
import { gmt7Date, gmt7DateStart, lastFinishedDays, singleDay, yesterdayRange } from "../src/shopee/time";
import shopTraffic from "./fixtures/shop_traffic.json";

// 2026-10-12 10:00 GMT+7
const NOW = Date.UTC(2026, 9, 12, 3, 0, 0);
const Y_START = Date.UTC(2026, 9, 10, 17, 0, 0) / 1000; // 2026-10-11 00:00 GMT+7

describe("GMT+7 days", () => {
  it("computes yesterday as Seller Centre's 'Hôm qua'", () => {
    expect(yesterdayRange(NOW)).toEqual({ date: "2026-10-11", start_time: Y_START, end_time: Y_START + 86399 });
    expect(gmt7Date(Y_START - 1)).toBe("2026-10-10");
  });

  it("accepts exactly one finished day and nothing else", () => {
    const day = (params: Record<string, string>) => singleDay(new URLSearchParams(params), NOW);
    expect(day({ period: "yesterday", start_time: String(Y_START), end_time: String(Y_START + 86399) })).toBe(
      "2026-10-11",
    );
    expect(day({ period: "yesterday" })).toBe("2026-10-11");
    expect(day({ period: "real_time", start_time: String(Y_START + 86400), end_time: String(Y_START + 120000) })).toBeNull();
    expect(day({ period: "past30days", start_time: String(Y_START - 29 * 86400), end_time: String(Y_START + 86399) })).toBeNull();
    // Today is not finished yet.
    expect(day({ period: "day", start_time: String(Y_START + 86400), end_time: String(Y_START + 2 * 86400 - 1) })).toBeNull();
    expect(day({ period: "day", dt: "2026-10-09" })).toBe("2026-10-09");
    expect(day({ period: "yesterday", dt: "2026-10-12" })).toBeNull();
  });
});

// Recorded on Juli's own Shopee shop, 2026-10-26 (no products / orders; formats only).
describe("recorded Seller Centre day shapes (2026-10-26)", () => {
  const CAPTURED = Date.UTC(2026, 9, 26, 3, 0, 0); // 2026-10-26 10:00 GMT+7
  const OCT1 = 1790787600; // 2026-10-01 00:00 GMT+7
  const OCT25 = OCT1 + 24 * 86400;
  const OCT26 = OCT1 + 25 * 86400;
  const fromUrl = (url: string) => singleDay(new URL(url).searchParams, CAPTURED);
  const SC = "https://banhang.shopee.vn";

  it("accepts a picked day: period=day, end = start + 86400 (the next midnight)", () => {
    expect(fromUrl(`${SC}/api/mydata/v2/product/overview/?start_time=1790787600&end_time=1790874000&period=day`)).toBe(
      "2026-10-01",
    );
    expect(
      fromUrl(
        `${SC}/api/mydata/v1/product/traffic/overview/?start_time=${OCT1}&end_time=${OCT1 + 86400}&period=day&order_type=confirmed`,
      ),
    ).toBe("2026-10-01");
    // 366 days back still maps to its own day.
    const old = OCT26 - 366 * 86400;
    expect(fromUrl(`${SC}/x?start_time=${old}&end_time=${old + 86400}&period=day`)).toBe(gmt7Date(old));
  });

  it("rejects period=day with end = start + 86399 (Shopee answers code 10006)", () => {
    expect(
      fromUrl(
        `${SC}/api/mydata/v1/product/traffic/overview/?start_time=${OCT1}&end_time=${OCT1 + 86399}&period=day&order_type=confirmed`,
      ),
    ).toBeNull();
  });

  it("keeps accepting yesterday (period=yesterday, end = start + 86399)", () => {
    expect(fromUrl(`${SC}/x?start_time=${OCT25}&end_time=${OCT25 + 86399}&period=yesterday&order_type=confirmed`)).toBe(
      "2026-10-25",
    );
    expect(fromUrl(`${SC}/x?start_time=${OCT25}&end_time=${OCT25 + 86400}&period=yesterday`)).toBeNull();
  });

  it("rejects today, partial days and multi-day aggregates", () => {
    expect(fromUrl(`${SC}/x?start_time=${OCT26}&end_time=${OCT26 + 86400}&period=day`)).toBeNull(); // unfinished
    expect(fromUrl(`${SC}/x?start_time=${OCT26}&end_time=${OCT26 + 36000}&period=real_time`)).toBeNull();
    expect(fromUrl(`${SC}/x?start_time=${OCT1 + 3600}&end_time=${OCT1 + 3600 + 86400}&period=day`)).toBeNull(); // not a midnight
    expect(fromUrl(`${SC}/x?start_time=${OCT1}&end_time=${OCT1 + 43200}&period=day`)).toBeNull(); // half a day
    expect(fromUrl(`${SC}/x?start_time=${OCT1}&end_time=${OCT1 + 2 * 86400}&period=day`)).toBeNull(); // two days
    expect(fromUrl(`${SC}/x?start_time=${OCT25 - 6 * 86400}&end_time=${OCT25 + 86399}&period=past7days`)).toBeNull();
    expect(fromUrl(`${SC}/x?start_time=${OCT25 - 29 * 86400}&end_time=${OCT25 + 86399}&period=past30days`)).toBeNull();
    expect(fromUrl(`${SC}/x?start_time=${OCT1}&end_time=${OCT1 + 7 * 86400}&period=week`)).toBeNull();
    expect(fromUrl(`${SC}/x?start_time=${OCT1}&end_time=${OCT1 + 31 * 86400}&period=month`)).toBeNull();
  });

  it("reads the traffic dashboard's dt=YYYYMMDD as that GMT+7 day, finished days only", () => {
    expect(fromUrl(`${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=20261001`)).toBe("2026-10-01");
    expect(fromUrl(`${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=20261025`)).toBe("2026-10-25");
    expect(fromUrl(`${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=20261026`)).toBeNull(); // today
    expect(fromUrl(`${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=20261340`)).toBeNull(); // no such day
    expect(fromUrl(`${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=2026101`)).toBeNull();
    expect(fromUrl(`${SC}/api/mydata/traffic/dashboard/overview/?period=past7days&dt=20261001`)).toBeNull();
    // The older forms still work.
    expect(fromUrl(`${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=2026-10-01`)).toBe("2026-10-01");
    expect(fromUrl(`${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=${OCT1}`)).toBe("2026-10-01");
  });

  it("maps a captured dt=20261001 shop traffic answer to 2026-10-01", () => {
    const mapped = mapCaptured({
      url: `${SC}/api/mydata/traffic/dashboard/overview/?period=day&dt=20261001`,
      body: shopTraffic,
      capturedAt: CAPTURED,
    });
    expect(mapped?.dataset).toBe("shop_traffic");
    expect(mapped?.date).toBe("2026-10-01");
    expect(mapped?.rows.length).toBeGreaterThan(0);
  });

  it("lists the last finished days newest first, and date ↔ GMT+7 midnight", () => {
    const days = lastFinishedDays(CAPTURED, 30);
    expect(days).toHaveLength(30);
    expect(days[0]).toBe("2026-10-25");
    expect(days[29]).toBe("2026-09-26");
    expect(gmt7DateStart("2026-10-01")).toBe(OCT1);
  });
});
