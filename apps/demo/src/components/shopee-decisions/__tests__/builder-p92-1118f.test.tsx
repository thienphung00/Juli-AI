import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import { HOUR_PROBLEM, MAX_FIRST_LINE, MAX_TITLE, buildVersion, initialForms, parseHour } from "../../../lib/shopee-decisions/builder-p92";
import { PriceDisplayPanel, unitPrice } from "../builder-p92/panels-listing";
import { SetPanel } from "../builder-p92/panels-offers";
import { HourIn } from "../builder-p92/shared";

const product = { item_id: "1001", name: "Sản phẩm thử" } as unknown as PickerProduct;
const ctx = { product, variations: [] };

describe("F1.7 · Shopee limits before So sánh", () => {
  it("a fixed voucher discount under 1 % of the minimum spend is refused in Vietnamese", () => {
    const f = initialForms();
    const bad = buildVersion("voucher", { ...f, voucher: { ...f.voucher, dtype: "amount", value: "1000", min: "500000" } }, ctx);
    expect(bad.version).toBeNull();
    expect(bad.problem).toContain("1% đơn tối thiểu");
    expect(bad.problem).toContain("₫5.000");
    expect(bad.problem).toContain("₫100.000");
    const ok = buildVersion("voucher", { ...f, voucher: { ...f.voucher, dtype: "amount", value: "5000", min: "500000" } }, ctx);
    expect(ok.problem).toBeNull();
  });

  it("parses hours as HH:mm", () => {
    expect(parseHour("00:00")).toBe(0);
    expect(parseHour("23:00")).toBe(23);
    expect(parseHour("08:30")).toBe(8);
    expect(parseHour("23:59")).toBe(23);
    expect(parseHour("08:60")).toBeNull();
    expect(parseHour("8")).toBe(8);
    expect(parseHour("24:00")).toBeNull();
    expect(parseHour("ab")).toBeNull();
  });

  it("a combo with 00:00 / 23:00 builds; a bad time is refused; minutes are kept with the hour message", () => {
    const f = initialForms();
    const combo = { ...f.combo, items: ["1001", "1002"], tiers: [{ qty: "2", value: "5" }, { qty: "3", value: "8" }], start: "2026-11-20", end: "2026-11-21" };
    const good = buildVersion("combo", { ...f, combo: { ...combo, startHour: "00:00", endHour: "23:00" } }, ctx);
    expect(good.problem).toBeNull();
    expect(good.version).toMatchObject({ start_hour: 0, end_hour: 23 });
    const bad = buildVersion("combo", { ...f, combo: { ...combo, startHour: "25:00" } }, ctx);
    expect(bad.problem).toBe(HOUR_PROBLEM);
    expect(HOUR_PROBLEM).toBe("Nhập giờ dạng HH:mm (00:00–23:59)");
    // E117: minutes are accepted (HH:mm) and kept in the card spec next to the hour
    const timed = buildVersion("combo", { ...f, combo: { ...combo, startHour: "08:30", endHour: "23:59" } }, ctx);
    expect(timed.problem).toBeNull();
    expect(timed.version).toMatchObject({ start_hour: 8, start_minute: 30, end_hour: 23, end_minute: 59 });
    expect(good.version).not.toHaveProperty("start_minute");
    expect(buildVersion("combo", { ...f, combo: { ...combo, startHour: "08:60" } }, ctx).problem).toBe(HOUR_PROBLEM);
  });

  it("the hour field shows its error next to it", () => {
    render(<HourIn label="Giờ bắt đầu" onChange={() => undefined} value="99" />);
    expect(screen.getByRole("alert")).toHaveTextContent(HOUR_PROBLEM);
    fireEvent.change(screen.getByRole("textbox", { name: "Giờ bắt đầu" }), { target: { value: "08:00" } });
  });

  it("the limits are Shopee's: title 120, one description constant", () => {
    expect(MAX_TITLE).toBe(120);
    expect(MAX_FIRST_LINE).toBe(300);
    const f = initialForms();
    expect(buildVersion("title", { ...f, title: { ...f.title, text: "x".repeat(121) } } as never, ctx).problem).toContain("120");
    expect(buildVersion("description_first_line", { ...f, description_first_line: { text: "x".repeat(301) } }, ctx).problem).toContain("300");
  });
});

const variation = (over: Record<string, unknown>) => ({ variation_id: "v1", name: "Set 3 miếng", list_price: 90000, selling_price: 85000, pack_count: 3, price_per_unit: 85000, stock: 12, ...over });

describe("F1.8 · current values the API has", () => {
  it("the variation panel lists the existing variations with price and stock", () => {
    const ctx = { variations: [variation({}), variation({ variation_id: "v2", name: "Lẻ 1 miếng", pack_count: 1, selling_price: 30000, stock: 4 })] };
    render(<SetPanel ctx={ctx as never} form={initialForms().variation_set} set={() => undefined} />);
    const cur = screen.getByTestId("p2-set-current");
    expect(cur).toHaveTextContent("Set 3 miếng · 85.000đ · tồn 12");
    expect(cur).toHaveTextContent("Lẻ 1 miếng · 30.000đ · tồn 4");
  });

  it("no variations: nothing is shown", () => {
    render(<SetPanel ctx={{ variations: [] } as never} form={initialForms().variation_set} set={() => undefined} />);
    expect(screen.queryByTestId("p2-set-current")).toBeNull();
  });

  it("giá mỗi đơn vị of a pack is the price divided by its size", () => {
    expect(unitPrice(variation({}) as never)).toBe(28333);
    expect(unitPrice(variation({ pack_count: 1, price_per_unit: 85000 }) as never)).toBe(85000);
    render(<PriceDisplayPanel ctx={{ variations: [variation({})] } as never} form={{ what: "price_display", text: "", stock: "" }} set={() => undefined} />);
    expect(screen.getByText(/Giá mỗi đơn vị: 28\.333đ/)).toBeInTheDocument();
  });
});
