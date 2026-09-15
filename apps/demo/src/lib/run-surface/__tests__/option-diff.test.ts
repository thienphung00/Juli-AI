import { describe, expect, it } from "vitest";

import {
  RUN_OPTION_FIELD_FALLBACK,
  buildOptionDiffRows,
  describeOptionField,
} from "../option-diff";

describe("buildOptionDiffRows", () => {
  it("renders a {from,to}-shaped field as struck-before/highlighted-after, both verbatim from the payload", () => {
    const rows = buildOptionDiffRows(
      { price: { from: "219000", to: "189000" } },
      "Áo thun cotton nam",
    );

    expect(rows).toEqual([{ field: "price", before: "219000", after: "189000" }]);
  });

  it("falls back to productName as the 'before' for a bare title field -- no from on the wire yet", () => {
    const rows = buildOptionDiffRows({ title: "Tiêu đề đã tối ưu" }, "Áo thun cotton nam");

    expect(rows).toEqual([
      { field: "title", before: "Áo thun cotton nam", after: "Tiêu đề đã tối ưu" },
    ]);
  });

  it("never fabricates a before for an unknown scalar field -- proposed value only", () => {
    const rows = buildOptionDiffRows({ stock: 42 }, "Áo thun cotton nam");

    expect(rows).toEqual([{ field: "stock", after: "42" }]);
    expect(rows[0]).not.toHaveProperty("before");
  });

  it("mutating the payload field changes the rendered row -- nothing derived client-side", () => {
    const before = buildOptionDiffRows({ price: { from: "219000", to: "189000" } }, "x");
    const after = buildOptionDiffRows({ price: { from: "219000", to: "179000" } }, "x");

    expect(before[0]!.after).toBe("189000");
    expect(after[0]!.after).toBe("179000");
  });

  it("renders one row per proposed_change field, in insertion order", () => {
    const rows = buildOptionDiffRows(
      { title: "New title", stock: 10 },
      "Old title",
    );

    expect(rows.map((r) => r.field)).toEqual(["title", "stock"]);
  });
});

describe("describeOptionField (issue #1908)", () => {
  it("maps a known field to its seller-facing Vietnamese label", () => {
    expect(describeOptionField("title")).toBe("Tiêu đề");
    expect(describeOptionField("price")).toBe("Giá");
  });

  it("returns the generic Vietnamese fallback for an unknown field -- never the raw key", () => {
    expect(describeOptionField("attach_staged_image")).toBe(RUN_OPTION_FIELD_FALLBACK);
    expect(describeOptionField("description")).toBe(RUN_OPTION_FIELD_FALLBACK);
    expect(describeOptionField("attach_staged_image")).not.toBe("attach_staged_image");
  });

  it("the fallback is the dictionary's run.option_field.fallback string and carries no raw identifier", () => {
    expect(RUN_OPTION_FIELD_FALLBACK).toBe("Thay đổi được đề xuất");
    expect(RUN_OPTION_FIELD_FALLBACK).not.toMatch(/[a-z]+_[a-z]+/);
  });
});
