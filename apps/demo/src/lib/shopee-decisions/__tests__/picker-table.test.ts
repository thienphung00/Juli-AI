import { describe, expect, it } from "vitest";

import { NO_FILTERS, addIds, categoriesOf, filterProducts, fold, marginBandOf, matchPasted, parseIds, removeId } from "../picker-table";
import { P_GLOVE, P_IDLE, P_LEMON, P_SPONGE, P_ZIP, pickerProducts } from "./builder-fixtures";

const all = pickerProducts().products;
const ids = (list: readonly { item_id: string }[]) => list.map((p) => p.item_id);

describe("P97 D85.12 · table picker logic", () => {
  it("searches by name (accent-insensitive) or by id", () => {
    expect(ids(filterProducts(all, { ...NO_FILTERS, q: "rua chen" }))).toEqual([P_SPONGE, P_LEMON]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, q: P_ZIP.slice(0, 6) }))).toEqual([P_ZIP]);
    expect(fold("Màng bọc Đẹp")).toBe("mang boc dep");
  });

  it("filters by ngành hàng, biên, CTOR giảm, có đề xuất, đang chạy QC and KOL", () => {
    expect(ids(filterProducts(all, { ...NO_FILTERS, category: "Găng tay" }))).toEqual([P_GLOVE]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, margin: "low" }))).toEqual([P_SPONGE]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, margin: "mid" }))).toEqual([P_ZIP]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, margin: "high" }))).toEqual([P_GLOVE]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, ctorDown: true }))).toEqual([P_GLOVE]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, hasProposal: true }))).toEqual([P_GLOVE]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, inAds: true }))).toEqual([P_ZIP]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, inKol: true }))).toEqual([P_SPONGE]);
    expect(ids(filterProducts(all, { ...NO_FILTERS, chip: "idle" }))).toEqual([P_IDLE]);
  });

  it("a product with no cost or no margin is 'chưa tính', never in a margin band", () => {
    const lemon = all.find((p) => p.item_id === P_LEMON)!;
    expect(marginBandOf(lemon)).toBe("unknown");
    expect(ids(filterProducts(all, { ...NO_FILTERS, margin: "unknown" }))).toContain(P_LEMON);
  });

  it("lists the categories once, sorted", () => {
    expect(categoriesOf(all)).toEqual(["Dụng cụ rửa chén", "Găng tay", "Túi đựng thực phẩm"]);
  });

  it("parses a pasted list of ids and reports the ones it does not know", () => {
    expect(parseIds(` ${P_ZIP},${P_GLOVE}\n${P_ZIP}; 999 \t`)).toEqual([P_ZIP, P_GLOVE, "999"]);
    const r = matchPasted(all, `${P_ZIP}\n${P_GLOVE}\n404`);
    expect(r.found).toEqual([P_ZIP, P_GLOVE]);
    expect(r.missing).toEqual(["404"]);
  });

  it("adds without duplicates, respects the cap, and removes", () => {
    expect(addIds(["a"], ["a", "b", "c"])).toEqual(["a", "b", "c"]);
    expect(addIds(["a"], ["b", "c"], 2)).toEqual(["a", "b"]);
    expect(removeId(["a", "b"], "a")).toEqual(["b"]);
  });
});
