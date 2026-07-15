import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, formatNumber, formatVND } from "./index";

describe("Vietnamese shared formatters", () => {
  it("formats money and numbers with the Vietnamese locale", () => {
    expect(formatVND(1250000)).toMatch(/1\.250\.000/);
    expect(formatNumber(1250000)).toBe("1.250.000");
  });

  it("formats dates in ICT instead of exposing ISO strings", () => {
    const instant = "2026-07-14T18:30:00Z";

    expect(formatDate(instant)).toContain("15");
    expect(formatDateTime(instant)).toMatch(/15.*01:30|01:30.*15/);
    expect(formatDateTime(instant)).not.toContain("2026-07-14T18:30:00Z");
  });
});
