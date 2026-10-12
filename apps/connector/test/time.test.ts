import { describe, expect, it } from "vitest";
import { gmt7Date, singleDay, yesterdayRange } from "../src/shopee/time";

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
