import { describe, expect, it } from "vitest";

import { isoToDisplay, parseDay } from "../../../components/date-field";
import { operatingFloorNote, skuOfVariation, variationRows } from "../../../components/shopee-analytics/product-page";
import { defaultXep, readRanking, xepParam } from "../params";
import type { ProductHeader, SkuCost } from "../types";

const q = (s: string) => new URLSearchParams(s);
const sku = (p: Partial<SkuCost> & { sku: string }) => ({ cost: { cogs_per_unit: 1000 }, floor: null, ...p }) as unknown as SkuCost;
const header = (variations: ProductHeader["variations"]) => ({ variations }) as unknown as ProductHeader;

describe("V11 dates read dd/mm/yyyy", () => {
  it("shows ISO as dd/mm/yyyy and parses it back", () => {
    expect(isoToDisplay("2026-10-05")).toBe("05/10/2026");
    expect(parseDay("05/10/2026")).toBe("2026-10-05");
    expect(parseDay("5/10/2026")).toBe("2026-10-05");
    expect(parseDay("2026-10-05")).toBe("2026-10-05");
    expect(parseDay("31/02/2026")).toBeNull();
    expect(parseDay("05/10")).toBeNull();
  });
});

describe("X1 the ranking default sort follows the KPI", () => {
  it("a Biên cuối card is sorted by biên, not by GMV/ngày", () => {
    expect(readRanking(q("kpi=bien&src=the_san_pham")).xep).toBe("bien");
    expect(readRanking(q("kpi=gmv")).xep).toBe("gmv");
    expect(readRanking(q("kpi=bien&xep=gmv")).xep).toBe("gmv");
    // P96b L1: every KPI ranks by its own number (CTR by CTR); an unknown KPI by ₫ GMV/ngày
    expect(defaultXep("ctr")).toBe("ctr");
    expect(defaultXep("views")).toBe("views");
    expect(defaultXep("nope")).toBe("gmv");
    expect(xepParam("bien", "bien")).toBeNull();
    expect(xepParam("bien", "gmv")).toBe("gmv");
  });
});

describe("V4 variation rows", () => {
  const skus = [sku({ sku: "G500002×3", variation_id: "v2", base_sku: "G500002" }), sku({ sku: "G500003×5", variation_id: "v3", base_sku: "G500003" })];
  const h = header([
    { variation_id: "v2", name: "Combo 3 hộp", seller_sku: "G500002", status: null },
    { variation_id: "v3", name: "Combo 5 hộp", seller_sku: "G500003", status: null },
    { variation_id: "m", name: "M", seller_sku: null, status: null },
    { variation_id: "l", name: "L", seller_sku: null, status: null },
  ]);
  it("finds the pack-keyed cost row of a variation and hides option rows without SKU or sales", () => {
    expect(skuOfVariation(h.variations[0], skus)?.sku).toBe("G500002×3");
    expect(variationRows(h, skus).map((v) => v.variation_id)).toEqual(["v2", "v3"]);
  });
  it("says why a floor is missing", () => {
    expect(operatingFloorNote(undefined)).toBe("chưa có đơn trong kỳ");
    expect(operatingFloorNote(sku({ sku: "a", cost: { cogs_per_unit: null } } as never))).toBe("chưa có giá vốn");
    expect(operatingFloorNote(sku({ sku: "a", floor: { reasons: { operating_floor: "missing:target_margin_rate" } } } as never))).toBe("chưa đặt biên mục tiêu");
  });
});
