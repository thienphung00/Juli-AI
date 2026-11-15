import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { applyFix, bannerText, fitToMode, KINDS, kindOf, newBanner, parseValue, ruleChecks, SHAPES, specOf, type Banner, type KindId, type Value } from "../banner";

/**
 * P100 S2-E: the banner rules are the server's (`services/shopee_builder/banner.py`). The shared
 * fixture pins the display text and the rule checks on both sides.
 */
const CASES = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../tests/fixtures/banner_cases.json"), "utf-8")) as {
  text: { kind: KindId; values: Record<string, Value>; head: string; sub: string }[];
  checks: { name: string; spec: { day_mode: "ngay_thuong" | "mega_sale"; banners: Banner[] }; checks: { code: string; banner: number | null; title: string }[] }[];
};

describe("banner text = the server's", () => {
  it.each(CASES.text.map((c) => [`${c.kind} ${JSON.stringify(c.values)}`, c] as const))("%s", (_name, c) => {
    expect(bannerText(c.kind, c.values)).toEqual({ head: c.head, sub: c.sub });
  });
});

describe("rule checks = the server's", () => {
  it.each(CASES.checks.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(ruleChecks(c.spec).map(({ code, banner, title }) => ({ code, banner, title }))).toEqual(c.checks);
  });
});

describe("editing", () => {
  const palette = ["#2F6B4F", "#F4EFE6", "#E07A3F"];
  it("a new banner takes the first free position of its shape, never bottom-left", () => {
    const voucher = newBanner(kindOf("voucher")!, [], palette, { values: { value: 10000 }, sources: { value: { card_id: "c", field: "change.after.value" } } });
    expect(voucher).toMatchObject({ shape: "the", position: "middle_right", colour: "#2F6B4F", values: { value: 10000 } });
    const combo = newBanner(kindOf("combo")!, [voucher], palette);
    expect(combo.position).toBe("bottom_right");
    expect(Object.values(SHAPES).flatMap((s) => s.positions.map(([p]) => p))).not.toContain("bottom_left");
    expect(KINDS.filter((k) => k.megaOnly).map((k) => k.id)).toEqual(["mega"]);
  });

  it("switching to Ngày thường drops the Mega Sale strip and keeps at most 3", () => {
    const strip = newBanner(kindOf("mega")!, [], palette);
    const rest = (["pct", "voucher", "combo"] as const).map((k) => newBanner(kindOf(k)!, [], palette));
    expect(fitToMode([strip, ...rest], "ngay_thuong").map((b) => b.kind)).toEqual(["pct", "voucher", "combo"]);
  });

  it("an overlap check moves the second banner to the free slot", () => {
    const a = newBanner(kindOf("voucher")!, [], palette);
    const b = { ...newBanner(kindOf("combo")!, [], palette), position: "middle_right" as const };
    const spec = specOf("toi_gian", "ngay_thuong", [a, b]);
    const overlap = spec.checks.find((c) => c.code === "overlap")!;
    expect(overlap.fix).toBe("Chuyển Combo sang Dưới phải.");
    expect(applyFix(spec, overlap)?.map((x) => x.position)).toEqual(["middle_right", "bottom_right"]);
  });

  it("typed values: money keeps digits, % keeps a decimal, text is text", () => {
    expect(parseValue("money", "10.000đ")).toBe(10000);
    expect(parseValue("pct", "7,5")).toBe(7.5);
    expect(parseValue("int", "")).toBeNull();
    expect(parseValue("text", "  Hộp 100 cái ")).toBe("Hộp 100 cái");
  });
});
