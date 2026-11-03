import { describe, expect, it } from "vitest";

import { chipFromChange, chipOf, chipPt, fmt, pc, pp, rangeText, sv, vnd } from "../format";

describe("Shopee screens number formats (artboards: 1.234.567đ, 3,66%)", () => {
  it("groups thousands with dots and decimals with a comma", () => {
    expect(fmt(1234567)).toBe("1.234.567");
    expect(fmt(1234.5, 1)).toBe("1.234,5");
    expect(fmt(-1500)).toBe("−1.500");
    expect(vnd(1234567)).toBe("1.234.567đ");
    expect(vnd(0)).toBe("0đ");
  });

  it("prints fractions and percent points as percents without a space", () => {
    expect(pc(0.0366)).toBe("3,66%");
    expect(pc(0.5, 0)).toBe("50%");
    expect(pp(18.4)).toBe("18,4%");
    expect(pp(10, 0)).toBe("10%");
  });

  it("signs a change with a real minus", () => {
    expect(sv(1500)).toBe("+1.500đ");
    expect(sv(-1500)).toBe("−1.500đ");
  });

  it("prints unknown as a dash, never 0", () => {
    expect(vnd(null)).toBe("—");
    expect(pc(undefined)).toBe("—");
    expect(pp(null)).toBe("—");
    expect(fmt(Number.NaN)).toBe("—");
    expect(sv(null)).toBe("—");
  });

  it("builds chips with the artboard's arrows", () => {
    expect(chipOf(100, 112.3).text).toBe("▲ 12,3%");
    expect(chipOf(100, 90).text).toBe("▼ 10,0%");
    expect(chipOf(0, 5).text).toBe("—");
    expect(chipPt(22.1, 20.9).text).toBe("▼ 1,2 điểm");
    expect(chipFromChange(-3.1).text).toBe("▼ 3,1%");
    expect(chipFromChange(null).up).toBeNull();
  });

  it("writes a window as dd/mm–dd/mm", () => {
    expect(rangeText({ from: "2026-10-04", to: "2026-11-02" })).toBe("04/10–02/11");
  });
});
