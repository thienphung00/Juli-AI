import { describe, expect, it } from "vitest";
import { isPageMessage } from "../src/platforms/shopee/content/messages";
import { CHANNEL, SELLER_CENTRE_ORIGIN, fillActive, marketActive, readerActive, schedulerActive } from "../src/platforms/shopee/config";
import { readersLabel } from "../src/platforms/shopee/popup/labels";

const NOW = Date.UTC(2026, 10, 3, 3, 0, 0);

describe("readersLabel", () => {
  it("says what the seller has to do after a stop, and nothing before the first run", () => {
    expect(readersLabel(undefined)).toBeNull();
    expect(readersLabel({ adsDone: [], blocked: { at: "x", reason: "captcha", page: "ads", until: NOW + 1 } }, NOW)).toContain("CAPTCHA");
    expect(readersLabel({ adsDone: [], blocked: { at: "x", reason: "login", page: "ads", until: NOW + 1 } }, NOW)).toContain("đăng nhập");
    expect(readersLabel({ adsDone: [], blocked: { at: "x", reason: "login", page: "ads", until: NOW - 1 }, lastRun: { day: "2026-11-02", at: "x", outcomes: {} } }, NOW)).toContain("2026-11-02");
    expect(readersLabel({ adsDone: [] }, NOW)).toBeNull();
  });
});

describe("feature flags", () => {
  it("T11: readers, scheduler, listing fill and market search follow the paired token's shop only", () => {
    expect(readerActive("ads", "a-paired-shop")).toBe(true);
    expect(readerActive("affiliate_kols", "another-shop")).toBe(true);
    expect(readerActive("affiliate", "another-shop")).toBe(true);
    expect(schedulerActive("another-shop")).toBe(true);
    expect(readerActive("ads", undefined)).toBe(false);
    expect(readerActive("ads", "")).toBe(false);
    expect(schedulerActive(undefined)).toBe(false);
    expect(fillActive("another-shop")).toBe(true);
    expect(fillActive(undefined)).toBe(false);
    expect(marketActive("another-shop")).toBe(true);
    expect(marketActive(undefined)).toBe(false);
  });
});

describe("page messages", () => {
  const event = (kind: string, origin = SELLER_CENTRE_ORIGIN) => ({ source: "w", origin, data: { channel: CHANNEL, kind } });
  it("accepts reader-result from Seller Centre's own window only", () => {
    expect(isPageMessage(event("reader-result"), "w", SELLER_CENTRE_ORIGIN, CHANNEL)).toBe(true);
    expect(isPageMessage(event("reader-result", "https://evil.example"), "w", SELLER_CENTRE_ORIGIN, CHANNEL)).toBe(false);
    expect(isPageMessage(event("reader-job"), "w", SELLER_CENTRE_ORIGIN, CHANNEL)).toBe(false); // SW -> page only
  });
});
