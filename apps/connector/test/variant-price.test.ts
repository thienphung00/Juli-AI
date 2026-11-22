// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { fillVariationPrices } from "../src/platforms/shopee/fill/fillers";
import { parseFillJob } from "../src/platforms/shopee/fill/job-types";
import { rawJob } from "./fill-job-helpers";

const PRICES = [
  { variation_id: "v20", name: "Combo 20 hộp", price: 16_000 },
  { variation_id: "v30", name: "Combo 30 hộp", price: 30_000 },
  { variation_id: "v40", name: "Combo 40 hộp", price: 40_000 },
  { variation_id: "v50", name: "Combo 50 hộp", price: 50_000 },
];

function priceJob(over: Record<string, unknown> = {}) {
  return rawJob("price", {
    variations: PRICES,
    open_path: "/portal/product/1001",
    ...over,
  });
}

describe("a price fill writes each variation's own price", () => {
  it("keeps four prices and does not replace the first with the last", async () => {
    const job = parseFillJob(priceJob());
    expect(job?.kind).toBe("price");
    expect(job?.payload).toMatchObject({
      kind: "price",
      price: { itemId: "1001", variations: PRICES.map((r) => ({ variationId: r.variation_id, price: r.price })) },
    });
    const parsed = job?.payload.kind === "price" ? job.payload.price.variations : [];
    expect(parsed.map((r) => r.price)).toEqual([16_000, 30_000, 40_000, 50_000]);
    expect(parsed[0]?.price).not.toBe(parsed[3]?.price);

    document.body.innerHTML = PRICES.map(
      (r) => `<div data-variation-id="${r.variation_id}"><span>${r.name}</span><input type="text" value="1"></div>`,
    ).join("");
    const out = await fillVariationPrices(
      { doc: document, sleep: async () => undefined, now: () => 0 },
      parsed,
    );
    expect(out.steps.every((s) => s.ok)).toBe(true);
    const values = PRICES.map((r) => (document.querySelector(`[data-variation-id="${r.variation_id}"] input`) as HTMLInputElement).value);
    expect(values).toEqual(["16000", "30000", "40000", "50000"]);
    expect(values[0]).not.toBe("40000");
  });

  it("drops a price job whose rows collapsed to one price for every variation", () => {
    expect(parseFillJob(priceJob({ variations: [{ variation_id: "v20", price: 16_000 }] }))?.payload).toMatchObject({
      price: { variations: [{ variationId: "v20", price: 16_000 }] },
    });
    expect(parseFillJob(priceJob({ open_path: "/portal/marketing/vouchers/new" }))).toBeNull();
    expect(parseFillJob(priceJob({ variations: [{ variation_id: "v20", price: 0 }] }))).toBeNull();
  });
});
