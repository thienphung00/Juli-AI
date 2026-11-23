// @vitest-environment jsdom
// batch-1123-a2 C-E116 + C-E111 against the read-only captures of 23/11 (c2/01-combo-form.md,
// c2/02-product-picker.md), fixture combo-live-1123.html (synthetic values):
// - E116: the tier boxes are found by their names (tiers.<i>.minAmount / tiers.<i>.discountPercentage),
//   the number boxes are type="numeric" (they were skipped before: tier 1 and Giới hạn đặt hàng);
//   tier 2 is written once the person's "Thêm mức ưu đãi" adds its row.
// - E111: Shopee's picker searches by Tên sản phẩm by default: a known product name is searched;
//   without one the id goes in and the search-type select is shown for the person to switch.
// The Connector never clicks (HTMLElement.prototype.click stays at 0 calls).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PANEL_ID } from "../src/core/fill/locate";
import { pickStep, textBoxesIn } from "../src/platforms/shopee/fill/controls";
import { tierRows } from "../src/platforms/shopee/fill/fillers";
import { runFillJob } from "../src/platforms/shopee/fill/job-run";
import { parseFillJob } from "../src/platforms/shopee/fill/job-types";
import { wireEds, type Wire } from "./eds-wire";
import { afterPanel, comboJob, jobHarness, personClicks } from "./fill-job-helpers";
import { loadPage } from "./fill-helpers";

let wire: Wire;
let click: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
  document.querySelectorAll(".eds-react-select-options-list").forEach((p) => p.remove());
  wire = wireEds(document);
  click = vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => {
  wire.stop();
  expect(click).not.toHaveBeenCalled();
  click.mockRestore();
});

const input = (sel: string) => document.querySelector(sel) as HTMLInputElement;
const panelText = () => document.getElementById(PANEL_ID)?.shadowRoot?.querySelector(".box")?.textContent ?? "";
const job = (over: Record<string, unknown> = {}) => comboJob({ starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", product_ids: ["1001"], purchase_limit: 1, ...over });
const harness = (raw: Record<string, unknown>) => jobHarness(raw, { path: "/portal/marketing/bundle/new" });

/** Shopee adds tier row N+1 with its own names (tiers.<N>.*), as the person's "Thêm mức ưu đãi" does. */
function shopeeAddsTier(): void {
  const body = document.getElementById("tiers")!;
  const rows = body.querySelectorAll("tr");
  const row = rows[0]!.cloneNode(true) as HTMLElement;
  row.querySelectorAll<HTMLInputElement>("input").forEach((i) => {
    i.name = i.name.replace(/^tiers\.0\./, `tiers.${rows.length}.`);
    i.value = "";
  });
  row.querySelector("td")!.textContent = String(rows.length + 1);
  body.append(row);
}

describe("C-E116: the combo form of 23/11", () => {
  it("type=numeric boxes are text boxes (tier quantity, Giới hạn đặt hàng)", () => {
    loadPage("combo-live-1123.html");
    expect(textBoxesIn(document.body).map((i) => i.name)).toEqual(expect.arrayContaining(["tiers.0.minAmount", "usageLimit"]));
  });

  it("tierRows finds tier 1 by its names, and tier N once Shopee adds it", () => {
    loadPage("combo-live-1123.html");
    expect(tierRows(document).map((r) => r.map((i) => i.name))).toEqual([["tiers.0.minAmount", "tiers.0.discountPercentage"]]);
    shopeeAddsTier();
    expect(tierRows(document).map((r) => r.map((i) => i.name))).toEqual([
      ["tiers.0.minAmount", "tiers.0.discountPercentage"],
      ["tiers.1.minAmount", "tiers.1.discountPercentage"],
    ]);
  });

  it("fills tier 1 and Giới hạn đặt hàng at once, highlights Thêm mức ưu đãi, and writes tier 2 when the person adds it", async () => {
    loadPage("combo-live-1123.html");
    const h = harness(job());
    let first = "";
    afterPanel(h, () => {
      first = panelText();
      personClicks(document.getElementById("add-tier"));
      shopeeAddsTier();
    });
    await runFillJob(h.deps);
    expect(first).not.toContain("Không thấy dòng «Mua … sản phẩm» của mức này");
    expect(first).toContain("Bấm «Thêm mức ưu đãi» rồi Juli điền: Mua 3 giảm 8%");
    expect([input('[name="tiers.0.minAmount"]').value, input('[name="tiers.0.discountPercentage"]').value]).toEqual(["2", "5"]);
    expect([input('[name="tiers.1.minAmount"]').value, input('[name="tiers.1.discountPercentage"]').value]).toEqual(["3", "8"]);
    expect(input('[name="usageLimit"]').value).toBe("1");
    expect(document.getElementById("add-tier")!.style.outline).not.toBe("");
    const detail = h.details.filter(Boolean).at(-1)!;
    expect(detail.fields.filter((f) => /^tier|purchase_limit/.test(f.key)).map((f) => [f.key, f.ok])).toEqual(
      expect.arrayContaining([["tier1_qty", true], ["tier1_value", true], ["tier2_qty", true], ["tier2_value", true], ["purchase_limit", true]]),
    );
    expect(wire.forbidden).toEqual([]);
  });
});

describe("C-E111: the product picker searches by name by default", () => {
  it("with a product name in the job, the name is searched and the step names the product and its row", async () => {
    loadPage("combo-live-1123.html");
    const raw = job({ product_names: ["Sản phẩm mẫu một"] });
    expect(parseFillJob(raw)).toMatchObject({ payload: { combo: { productNames: { "1001": "Sản phẩm mẫu một" } } } });
    const h = harness(raw);
    afterPanel(h, () => document.getElementById("picker")!.removeAttribute("hidden"));
    await runFillJob(h.deps);
    expect(input("#psearch").value).toBe("Sản phẩm mẫu một");
    expect(panelText()).toContain("Bấm «Thêm sản phẩm», tìm «Sản phẩm mẫu một», tick dòng Mã: 1001, bấm Xác nhận của hộp chọn");
    // the name search finds it under Shopee's default search type
    personClicks(document.querySelector("[data-search]"));
    expect((document.querySelector('#ptable tr[data-id="1001"]') as HTMLElement).hasAttribute("hidden")).toBe(false);
    // the select's own type-to-search box is never taken for the search box
    expect(input(".custom-eds-react-select-selection-search-input").value).toBe("");
  });

  it("without a name: the id goes in, the search-type select is highlighted and the step says to switch to Mã sản phẩm", async () => {
    loadPage("combo-live-1123.html");
    const h = harness(job());
    afterPanel(h, () => document.getElementById("picker")!.removeAttribute("hidden"));
    await runFillJob(h.deps);
    expect(input("#psearch").value).toBe("1001");
    expect(document.getElementById("ptype")!.style.outline).not.toBe("");
    expect(panelText()).toContain("Bấm «Thêm sản phẩm», đổi ô tìm sang «Mã sản phẩm», tìm 1001, tick, bấm Xác nhận của hộp chọn");
  });

  it("pickStep falls back to the id step when any product has no name; product_names must match product_ids", () => {
    expect(pickStep("Thêm sản phẩm", ["1", "2"], { "1": "A" })).toContain("đổi ô tìm sang «Mã sản phẩm»");
    expect(parseFillJob(job({ product_names: ["A", "B"] }))).toBeNull();
  });
});
