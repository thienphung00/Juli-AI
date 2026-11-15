import { describe, expect, it } from "vitest";
import type { VariationRow } from "../../../lib/shopee-decisions/builder-api";
import { unitText } from "../builder-p92/variations";

const v = (over: Partial<VariationRow>) => ({ price_per_unit: 59_000, ...over }) as VariationRow;

describe("unitText", () => {
  it("prints the price per 100 ml when the listing states a content", () => {
    expect(unitText(v({ price_per_measure: 11_800, measure_label: "100 ml" }))).toBe("11.800đ/100 ml");
  });
  it("falls back to the price per sold unit", () => {
    expect(unitText(v({}))).toBe("59.000đ/đơn vị");
  });
});
