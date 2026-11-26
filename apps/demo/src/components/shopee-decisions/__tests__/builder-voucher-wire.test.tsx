import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { vnCount, vnd } from "../../../lib/shopee-analytics/format";
import type { BuilderEvaluation } from "../../../lib/shopee-decisions/builder-api";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";
import { ResultCard } from "../builder-p92/results";

/**
 * #78 / #87: the builder's answer as the backend writes it (`/builder/evaluate`, a 10 % voucher
 * capped at 3.000đ on the synthetic reco shop). The file is regenerated and guarded by
 * tests/unit/test_r2_builder_voucher_wire_fixture.py, so the offers here are the engine's own.
 */
const WIRE = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../tests/fixtures/builder_voucher_wire.json"), "utf-8")) as BuilderEvaluation;

const result = (): OptionResult => {
  const r = WIRE.versions[0]?.result;
  if (!r) throw new Error("the fixture has no result");
  return r;
};

describe("builder wire: cost.offers end to end", () => {
  it("each offer's uses × per use = its total, and Σ totals + fixed = cost.total", () => {
    const { cost } = result();
    const offers = cost.offers ?? [];
    expect(offers.length).toBeGreaterThan(0);
    for (const o of offers) expect(o.expected_uses * o.per_use).toBeCloseTo(o.total, 3);
    const sum = offers.reduce((s, o) => s + o.total, 0) + (cost.fixed ?? 0);
    expect(sum).toBeCloseTo(cost.total, 3);
  });

  it("the voucher offer carries its max discount", () => {
    const o = result().cost.offers?.find((x) => x.label === "voucher");
    expect(o?.max_discount?.cap).toBe(3000);
    expect(o?.max_discount?.binding_orders).toBeGreaterThan(0);
    expect(o?.max_discount?.binding_orders).toBeLessThanOrEqual(o?.max_discount?.qualifying_orders ?? 0);
  });

  it("the Số liệu panel shows the offer exactly as the wire gives it", () => {
    const r = result();
    const o = r.cost.offers?.[0];
    if (!o) throw new Error("no offer");
    render(<ResultCard name="V" result={r} />);
    fireEvent.click(screen.getByRole("button", { name: /số liệu/i }));
    const row = within(screen.getByTestId("p3-numbers")).getByTestId("p3-offer-0");
    expect(row).toHaveTextContent("Voucher");
    expect(row).toHaveTextContent(`${vnCount(o.expected_uses)} × ${vnd(o.per_use)} = ${vnd(o.total)}`);
  });
});
