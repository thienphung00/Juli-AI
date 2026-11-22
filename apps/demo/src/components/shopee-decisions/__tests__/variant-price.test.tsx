import { configure, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { P_ZIP, fakeBuilder, variationList } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import type { VariationRow } from "../../../lib/shopee-decisions/builder-api";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { BuilderP92View } from "../builder-p92";
import { ResultCard } from "../builder-p92/results";
import { renderReco } from "./harness";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";

configure({ asyncUtilTimeout: 4000 });

const base = variationList().variations[0]!;

function pack(id: string, name: string, price: number): VariationRow {
  return { ...base, variation_id: id, name, sku: id, list_price: price, selling_price: price, pack_count: Number(id.slice(1)), price_per_unit: Math.round(price / Number(id.slice(1))), orders_30d: 0, stock: 8 };
}

const COMBOS = [pack("v20", "Combo 20 hộp", 20_000), pack("v30", "Combo 30 hộp", 30_000), pack("v40", "Combo 40 hộp", 40_000), pack("v50", "Combo 50 hộp", 50_000)];

afterEach(() => {
  // @ts-expect-error jsdom has no matchMedia unless a test defines it
  delete window.matchMedia;
});

describe("Giá bán on a product with four variations", () => {
  it("shows one row per variation and a −20% preview uses that variation's price", async () => {
    const list = variationList();
    const builder = fakeBuilder({ variations: { ...list, variations: COMBOS } });
    renderReco(<BuilderP92View from="quyet-dinh" productId={null} />, fakeReco(), { builder });
    fireEvent.click(await screen.findByTestId(`p2-prod-${P_ZIP}`));
    await waitFor(() => expect(screen.getByTestId("p2-vnext")).toBeEnabled());
    fireEvent.click(screen.getByTestId("p2-vnext"));
    await screen.findByTestId("p2-kinds");
    fireEvent.click(screen.getByTestId("p2-kind-price_flash"));
    fireEvent.click(screen.getByTestId("p2-knext"));

    const rows = await screen.findByTestId("p2-varrows");
    expect(rows.querySelectorAll("[data-testid^='p2-var-']")).toHaveLength(4);
    for (const v of COMBOS) {
      const row = screen.getByTestId(`p2-var-${v.variation_id}`);
      expect(row).toHaveTextContent(v.name);
      expect(row).toHaveTextContent(`${v.selling_price!.toLocaleString("vi-VN")}đ`);
    }

    fireEvent.change(screen.getByRole("textbox", { name: "Thay đổi · Combo 20 hộp" }), { target: { value: "-20" } });
    const preview = screen.getByTestId("p2-next-v20");
    expect(preview).toHaveTextContent("16.000đ");
    expect(preview).not.toHaveTextContent("40.000đ");
    expect(screen.getByTestId("p2-var-v50")).toHaveTextContent("50.000đ");

    await waitFor(() => {
      const sent = builder.calls.filter((c) => c.name === "evaluate").at(-1)?.args[0] as
        | { variations: { variation_id: string; final_price?: number }[] }[]
        | undefined;
      const version = sent?.[0];
      const by = Object.fromEntries((version?.variations ?? []).map((r) => [r.variation_id, r.final_price]));
      expect(version?.variations).toHaveLength(4);
      expect(by).toEqual({ v20: 16_000, v30: 30_000, v40: 40_000, v50: 50_000 });
      expect(by.v20).not.toBe(40_000);
    });
  });
});

describe("a result with no figure", () => {
  it("does not say ước tính", () => {
    const result = {
      kind: "price",
      label: "Đổi giá",
      days: 30,
      horizon: "duration",
      drivers: ["ctor"],
      estimable: false,
      basis: "insufficient",
      basis_weak: false,
      reason_text: "Chưa ước tính được",
      delta: { profit: null, gmv: { value: null, pct: null }, orders: { value: null, pct: null, note: "Chưa ước tính được" } },
      build_up: [],
      drivers_pct: [],
      cost: { total: 0, break_even_orders: null, break_even_aov: null, text: "" },
      after: { days: 30, label: "30 ngày", gmv_before: null, gmv_after: null, profit_before: null, profit_after: null },
      per_30d: { profit: null, gmv: null, orders: null },
      detail: { before: { profit: null, gmv: null, orders: null }, low: null, likely: null, high: null },
      notes: ["Chưa ước tính được"],
    } as unknown as OptionResult;
    renderReco(<ResultCard name="Giá" result={result} />, fakeReco(), {});
    expect(document.body.textContent ?? "").not.toMatch(/ước tính/);
    expect(screen.getByTestId("p3-verdict")).toHaveTextContent("—");
  });
});
