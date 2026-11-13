import { describe, expect, it } from "vitest";
import { inMode, roiText, shift } from "..";

describe("P100 shared metrics", () => {
  it("shows ROI as points, not percent", () => {
    expect(roiText(5.4)).toBe("5,4");
    expect(roiText(null)).toBe("—");
  });
  it("marks a rise good or bad by the metric's direction", () => {
    expect(shift(0.12)).toEqual({ text: "▲ 12 %", tone: "up" });
    expect(shift(0.12, -1)).toEqual({ text: "▲ 12 %", tone: "down" });
    expect(shift(-0.034)?.text).toBe("▼ 3,4 %");
    expect(shift(null)).toBeNull();
  });
  it("divides summed values by days only in Trung bình / ngày", () => {
    expect(inMode(300, 30, "total")).toBe(300);
    expect(inMode(300, 30, "avg")).toBe(10);
  });
});
