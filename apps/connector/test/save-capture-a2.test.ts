// @vitest-environment jsdom
// batch-1123-a2 C-K2 + C-E120 (contract K2): after Shopee's own save the job is reported `saved`
// WITH `captured_ref` = the new object's numeric id (the save answer's, else the list row it lands
// on); the combo save's redirect to Khuyến Mãi của Shop's list (/portal/marketing/list/discount/,
// E118) is a save; an undo whose confirm dialog closed and whose row is gone is `saved` (E120).
// ASSUMED shapes (captures 3 and 4 pending): the list row shows the id in a link
// (/bundle/<id>, ?promotion_id=<id>, …) or in a cell of its own ("ID: <id>" / the bare number);
// the confirm is a dialog whose text says Xóa / Kết thúc / Xác nhận. Every value is synthetic.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PANEL_ID } from "../src/core/fill/locate";
import { runFillJob } from "../src/platforms/shopee/fill/job-run";
import { parseFillJob } from "../src/platforms/shopee/fill/job-types";
import { capturedId, END_MARK, endedNow, savedOn } from "../src/platforms/shopee/fill/revert";
import { programmeIdFrom, savedSignal } from "../src/platforms/shopee/fill/saved";
import { wireEds, type Wire } from "./eds-wire";
import { comboJob, jobHarness, rawJob, voucherJob } from "./fill-job-helpers";
import { loadPage } from "./fill-helpers";

let wire: Wire;
let click: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
  wire = wireEds(document);
  click = vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => {
  wire.stop();
  expect(click).not.toHaveBeenCalled();
  click.mockRestore();
});

const COMBO_NAME = "Combo mẫu a2";
const combo = () => parseFillJob(comboJob({ name: COMBO_NAME, starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", product_ids: ["1001"] }))!;
/** Khuyến Mãi của Shop's list (discountType=all) with the new combo's row. */
const discountList = (cells: string) => `<div id="app"><table><tbody class="eds-react-table-tbody">
  <tr class="eds-react-table-row"><td><div>Chương trình mẫu khác</div></td><td>Đang diễn ra</td><td><a href="/portal/marketing/discount/111111111111111">Chi tiết</a></td></tr>
  <tr class="eds-react-table-row" id="new"><td><div>${COMBO_NAME}</div><div>Combo Khuyến Mãi</div></td><td>Sắp diễn ra</td>${cells}</tr>
</tbody></table></div>`;

describe("C-K2: where a save lands", () => {
  it("E118: the combo save redirect to /portal/marketing/list/discount/ (trailing slash) is a save; the form is not", () => {
    expect(savedOn(document, { pathname: "/portal/marketing/list/discount/" }, combo())).toBe(true);
    expect(savedOn(document, { pathname: "/portal/marketing/bundle/list" }, combo())).toBe(true);
    expect(savedOn(document, { pathname: "/portal/marketing/bundle/new" }, combo())).toBe(false);
    expect(savedOn(document, { pathname: "/portal/marketing/vouchers/list/" }, parseFillJob(voucherJob())!)).toBe(true);
  });

  it("the id comes from the row's link, else from a cell that shows it (never a product's «Mã:»)", () => {
    document.body.innerHTML = discountList(`<td><a href="/portal/marketing/bundle/528900000000001">Chi tiết</a></td>`);
    expect(capturedId(document, combo())).toBe("528900000000001");
    document.body.innerHTML = discountList(`<td><a href="/portal/marketing/list/discount/?promotion_id=528900000000002">Sửa</a></td>`);
    expect(capturedId(document, combo())).toBe("528900000000002");
    document.body.innerHTML = discountList(`<td><span>ID: 528900000000003</span></td>`);
    expect(capturedId(document, combo())).toBe("528900000000003");
    document.body.innerHTML = discountList(`<td><span>Mã: 40500000001</span></td>`);
    expect(capturedId(document, combo())).toBeNull();
  });

  it("programme forms capture too: Chương Trình Của Shop by its name", () => {
    const job = parseFillJob(
      rawJob("product_discount", {
        open_path: "/portal/marketing/discount/create",
        name: COMBO_NAME,
        starts_at: "09:00 25-11-2026",
        ends_at: "21:00 28-11-2026",
        product_ids: ["1001"],
        variations: [{ variation_id: "11", discount_pct: 12, name: "Hộp 1" }],
      }),
    )!;
    document.body.innerHTML = discountList(`<td><a href="/portal/marketing/discount/528900000000004">Chi tiết</a></td>`);
    expect(capturedId(document, job)).toBe("528900000000004");
  });

  it("the save answer's id: voucher / combo / programme create POSTs (patterns, capture 3 pending)", () => {
    expect(savedSignal({ method: "POST", pathname: "/api/marketing/v4/discount/create_discount", body: { data: { discount_id: 9001 } } })).toEqual({ ref: "9001" });
    expect(savedSignal({ method: "POST", pathname: "/api/marketing/v3/add_on_deal/create", body: { add_on_deal_id: "9002" } })).toEqual({ ref: "9002" });
    expect(programmeIdFrom({ data: { promotion_id: "x" } })).toBeNull();
  });
});

describe("C-K2: saved carries captured_ref", () => {
  /** Runs the combo fill; once filled, the person's save lands on the discount list (SPA: same page). */
  async function saveCombo(cells: string, options: { lateMs?: number; savedRef?: string } = {}) {
    loadPage("combo-live-1123.html");
    const h = jobHarness(comboJob({ name: COMBO_NAME, starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", product_ids: ["1001"] }), { path: "/portal/marketing/bundle/new" });
    if (options.savedRef) h.deps.savedRef = () => options.savedRef!;
    const sleep = h.deps.sleep;
    let landedAt = -1;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (landedAt < 0 && h.reports.length >= 2 && h.clock.t > 60_000) {
        landedAt = h.clock.t;
        document.body.innerHTML = discountList(options.lateMs ? "<td></td>" : cells);
        h.deps.loc.pathname = "/portal/marketing/list/discount/";
      } else if (options.lateMs && landedAt >= 0 && h.clock.t - landedAt >= options.lateMs && !document.querySelector("#new a")) {
        document.querySelector("#new td:last-child")!.innerHTML = cells.replace(/^<td>|<\/td>$/g, "");
      }
    };
    await runFillJob(h.deps);
    return h;
  }

  it("E118: the redirect is seen and `saved` goes with the row's id", async () => {
    const h = await saveCombo(`<td><a href="/portal/marketing/bundle/528900000000001">Chi tiết</a></td>`);
    const saved = h.reports.map((r, i) => [r[1], h.refs[i]]).filter(([s]) => s === "saved");
    expect(saved).toEqual([["saved", "528900000000001"]]);
    expect(h.reports.map((r) => r[1])).not.toContain("captured");
  });

  it("the save answer's id (page hook) is used when the row shows none", async () => {
    const h = await saveCombo(`<td></td>`, { savedRef: "528900000000009" });
    expect(h.reports.filter((r) => r[1] === "saved").map((_, i, all) => all.length)).toEqual([1]);
    expect(h.refs[h.reports.findIndex((r) => r[1] === "saved")]).toBe("528900000000009");
  });

  it("a row id that draws late: `saved` first without it, then `saved` again with it", async () => {
    const h = await saveCombo(`<td><a href="/portal/marketing/bundle/528900000000005">Chi tiết</a></td>`, { lateMs: 10_000 });
    const saved = h.reports.map((r, i) => [r[1], h.refs[i]]).filter(([s]) => s === "saved");
    expect(saved).toEqual([
      ["saved", undefined],
      ["saved", "528900000000005"],
    ]);
  });
});

describe("C-E120: the undo's delete is seen", () => {
  const comboEnd = () => parseFillJob(rawJob("combo_end", { mode: "revert", open_path: "/portal/marketing/bundle/list", name: COMBO_NAME }))!;
  const list = () => {
    document.body.innerHTML = `<div id="app"><table><tbody class="eds-react-table-tbody">
      <tr class="eds-react-table-row"><td><div>Combo mẫu khác</div></td><td>Đang diễn ra</td><td><span>Xóa</span></td></tr>
      <tr class="eds-react-table-row" id="crow"><td><div>${COMBO_NAME}</div></td><td>Sắp diễn ra</td><td><span id="cdel" ${END_MARK}="1">Xóa</span></td></tr>
    </tbody></table></div>`;
  };
  const confirm = () =>
    document.body.insertAdjacentHTML("beforeend", `<div class="eds-react-modal" role="dialog" id="confirm"><div>Xác nhận xóa Combo Khuyến Mãi?</div><span>Hủy</span><span>Xóa</span></div>`);

  it("confirm seen with the row there, then dialog closed and row gone: ended", () => {
    list();
    const job = comboEnd();
    expect(endedNow(document, job)).toBe(false);
    confirm();
    expect(endedNow(document, job)).toBe(false);
    document.getElementById("confirm")!.remove();
    document.getElementById("crow")!.remove();
    expect(endedNow(document, job)).toBe(true);
  });

  it("confirm cancelled (dialog closed, row still there): not ended", () => {
    list();
    const job = comboEnd();
    confirm();
    expect(endedNow(document, job)).toBe(false);
    document.getElementById("confirm")!.remove();
    expect(endedNow(document, job)).toBe(false);
  });

  it("a row that only vanishes with no confirm seen: not ended", () => {
    list();
    const job = comboEnd();
    expect(endedNow(document, job)).toBe(false);
    document.getElementById("crow")!.remove();
    expect(endedNow(document, job)).toBe(false);
  });

  it("end to end: Xóa highlighted, the person confirms Shopee's dialog, the row goes: `saved`", async () => {
    loadPage("bundle-list.html");
    const h = jobHarness(rawJob("combo_end", { mode: "revert", open_path: "/portal/marketing/bundle/list", name: "JC-2611-0009 V1" }));
    const sleep = h.deps.sleep;
    let step = 0;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (!h.reports.some((r) => r[1] === "filled")) return;
      step += 1;
      if (step === 2) confirm();
      if (step === 4) {
        document.getElementById("confirm")!.remove();
        document.getElementById("crow")!.remove();
      }
    };
    await runFillJob(h.deps);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled", "saved"]);
    expect(wire.forbidden).toEqual([]);
  });
});
