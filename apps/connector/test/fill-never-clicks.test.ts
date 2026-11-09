// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { FORBIDDEN_PRESS, unsafePress } from "../src/fill/controls";
import { runFillJob } from "../src/fill/job-run";
import { PANEL_ID } from "../src/fill/locate";
import { runFill } from "../src/fill/run";
import { parseFillRequest } from "../src/fill/types";
import { wireEds } from "./eds-wire";
import { adsJob, affiliateJob, comboJob, jobHarness, rawJob, voucherJob } from "./fill-job-helpers";
import { DESCRIPTION_FIELD, harness, loadPage, rawRequest, watchForbidden } from "./fill-helpers";

const FORBIDDEN_EVENTS = ["click", "submit", "mousedown", "mouseup", "pointerdown", "pointerup", "dblclick", "keydown", "keyup", "keypress"];
const request = (over: Record<string, unknown> = {}) => ({ ok: true as const, value: parseFillRequest(rawRequest(over))! });

beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
});
let watch: ReturnType<typeof watchForbidden> | undefined;
afterEach(() => watch?.stop());

describe("a fill never presses, submits or navigates", () => {
  it.each([
    ["the title", request(), "edit-labels.html"],
    ["the description", request({ change_kind: "description_first_line", fields: [DESCRIPTION_FIELD] }), "edit-labels.html"],
    ["a rich editor", request({ change_kind: "description_first_line", fields: [DESCRIPTION_FIELD] }), "edit-contenteditable.html"],
    ["an unknown layout", request(), "edit-unknown.html"],
    ["a page-only card", request({ change_kind: "listing_hide", fields: [], page_only: true }), "edit-labels.html"],
    ["a variation checklist", request({ change_kind: "variation_restructure", fields: [], checklist: [{ order: 1, field: "Phân loại 1", after: "x", copy: "x" }] }), "edit-labels.html"],
  ])("%s", async (_name, reply, page) => {
    loadPage(page);
    const hrefBefore = window.location.href;
    watch = watchForbidden();
    await runFill(harness(reply).deps);
    expect(watch.click).not.toHaveBeenCalled();
    expect(watch.submit).not.toHaveBeenCalled();
    expect(watch.requestSubmit).not.toHaveBeenCalled();
    expect(watch.seen).toEqual([]); // no click / submit / mouse / key event reached the page
    for (const type of watch.dispatched) {
      expect(FORBIDDEN_EVENTS).not.toContain(type);
      expect(["input", "change"]).toContain(type); // the only events a fill dispatches
    }
    expect(window.location.href).toBe(hrefBefore);
    // the page's own buttons were not even touched
    for (const id of ["save", "update", "confirm", "hide"]) {
      const button = document.getElementById(id);
      if (button) expect(button.getAttribute("data-juli-filled")).toBeNull();
    }
  });
});

// The job fillers (voucher, ads, affiliate, title) DO press ordinary controls -- open a select,
// choose a radio, tick a row, open a pencil popup, add a tier row -- but never a button that saves,
// sends, confirms, deletes or cancels, and never anything else a keyboard or a form would do.
describe("a job fill never presses Shopee's save / confirm / send", () => {
  const titleJob = rawJob("title", {
    open_path: "/portal/product/1001",
    fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 100, value: "Tên mới của sản phẩm mẫu" }],
  });
  it.each([
    ["a shop voucher", voucherJob(), "voucher-new.html"],
    ["a percentage voucher", voucherJob({ discount: { type: "percent", value: 10, max: { mode: "limited", value: 20000 } } }), "voucher-new.html"],
    ["a product voucher", voucherJob({ usecase: 2, product_ids: ["1001", "1002"], display: "private", open_path: "/portal/marketing/vouchers/new?usecase=2" }), "voucher-new.html"],
    ["an ads budget", adsJob({ budget: { mode: "daily", value: 150000 } }), "ads-edit.html"],
    ["an ads budget, unlimited", adsJob({ budget: { mode: "unlimited" } }), "ads-edit.html"],
    ["an ads ROAS", adsJob({ roas: { mode: "custom", value: 3 } }), "ads-edit.html"],
    ["an affiliate commission", affiliateJob(), "affiliate-open.html"],
    ["a percentage combo, one tier", comboJob({ tiers: [{ qty: 2, value: 10 }] }), "combo-tiers.html"],
    ["an amount combo, three tiers", comboJob({ discount_type: "amount", tiers: [{ qty: 2, value: 5000 }, { qty: 3, value: 9000 }, { qty: 5, value: 20000 }] }), "combo-tiers.html"],
    ["a special-price combo with no limit", comboJob({ discount_type: "special_price", purchase_limit: undefined, tiers: [{ qty: 2, value: 90000 }, { qty: 4, value: 160000 }] }), "combo-tiers.html"],
    ["a combo on a page that is not the form", comboJob(), "edit-unknown.html"],
    ["a title", titleJob, "edit-ory-recon.html"],
    ["a page that is not the expected form", voucherJob(), "edit-unknown.html"],
  ])("%s", async (_name, raw, page) => {
    loadPage(page);
    const wire = wireEds(document);
    const hrefBefore = window.location.href;
    watch = watchForbidden();
    await runFillJob(jobHarness(raw).deps);
    expect(wire.forbidden).toEqual([]); // no Xác nhận / Lưu lại / Hủy / Loại bỏ reached the page
    expect(watch.submit).not.toHaveBeenCalled();
    expect(watch.requestSubmit).not.toHaveBeenCalled();
    for (const type of watch.seen) expect(type).toBe("click"); // no mouse / pointer / key / submit event
    for (const type of watch.dispatched) expect(["input", "change"]).toContain(type);
    for (const target of watch.click.mock.contexts as HTMLElement[]) {
      expect(unsafePress(target), target.outerHTML.slice(0, 80)).toBeNull();
      expect(FORBIDDEN_PRESS.test((target.textContent ?? "").trim().toLocaleLowerCase("vi"))).toBe(false);
    }
    expect(window.location.href).toBe(hrefBefore);
    for (const id of ["submit", "cancel", "budget-ok", "roas-ok", "comm-ok", "pconfirm", "save"]) {
      expect(document.getElementById(id)?.getAttribute("data-juli-filled") ?? null).toBeNull();
    }
    wire.stop();
  });
});

describe("the source never presses anything", () => {
  const sources = import.meta.glob(["../src/fill/*.ts", "../src/background/fill.ts", "../src/background/fill-jobs.ts"], {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;
  const files = Object.entries(sources);
  const stripComments = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  it("covers every fill source file", () => {
    expect(files.map(([name]) => name.replace("../src/", "")).sort()).toEqual([
      "background/fill-jobs.ts",
      "background/fill.ts",
      "fill/controls.ts",
      "fill/fillers.ts",
      "fill/job-panel.ts",
      "fill/job-run.ts",
      "fill/job-types.ts",
      "fill/locate.ts",
      "fill/panel.ts",
      "fill/run.ts",
      "fill/saved.ts",
      "fill/types.ts",
      "fill/write.ts",
    ]);
  });

  // controls.ts is the one file that presses, through press() only (one `.click()` in the source),
  // and the one that looks for labelled buttons ("Thêm mức ưu đãi", "Tìm kiếm"); press() refuses
  // the save / confirm / send texts (tested in fill-controls.test.ts).
  it("has exactly one .click() call, inside press()", () => {
    const controls = stripComments(sources["../src/fill/controls.ts"] as string);
    expect(controls.match(/\.click\s*\(/g)).toHaveLength(1);
    expect(controls).toMatch(/if \(unsafePress\(el\) !== null\) return false;\s*el\.click\(\);/);
  });

  it.each(files)("%s", (name, source) => {
    const code = stripComments(source);
    const isControls = name.endsWith("fill/controls.ts");
    for (const banned of [
      ...(isControls ? [] : [/\.click\s*\(/]),
      /\.submit\s*\(/,
      /requestSubmit/,
      /new\s+(Mouse|Pointer|Keyboard|Touch)Event/,
      /new\s+Event\(\s*["'](click|submit|mousedown|mouseup|keydown|keyup)/,
      /dispatchEvent\([^)]*["'](click|submit)/,
      /location\.(assign|replace|href\s*=)/,
      /\.(open|navigate)\s*\(/,
      /\bfetch\s*\(/,
      /XMLHttpRequest/,
      /document\.cookie/,
      // it never goes looking for the page's buttons or forms (it has no business with them)
      ...(isControls ? [] : [/querySelector(All)?\([^)]*(button|submit|form)/i, /getElementsByTagName\(\s*["'](button|form)/i, /closest\(\s*["']form/i]),
    ]) {
      expect(code, `${banned}`).not.toMatch(banned);
    }
  });
});
