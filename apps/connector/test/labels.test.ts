import { describe, expect, it } from "vitest";
import { isPageMessage } from "../src/content/messages";
import { CHANNEL, SELLER_CENTRE_ORIGIN, PILOT_SHOP_IDS, readerActive, schedulerActive } from "../src/config";
import { readersLabel } from "../src/popup/labels";

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
  it("the pilot build turns the readers on for any paired shop, and never without a shop", () => {
    expect(PILOT_SHOP_IDS).toContain("*");
    expect(readerActive("ads", "s1")).toBe(true);
    expect(readerActive("ads", undefined)).toBe(false);
    expect(schedulerActive("s1")).toBe(true);
    expect(schedulerActive(undefined)).toBe(false);
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
