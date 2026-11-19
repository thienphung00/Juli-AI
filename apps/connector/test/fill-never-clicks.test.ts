// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runFillJob } from "../src/platforms/shopee/fill/job-run";
import { PANEL_ID } from "../src/core/fill/locate";
import { runFill } from "../src/platforms/shopee/fill/run";
import { parseFillRequest } from "../src/core/fill/types";
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

// 0.3.28 (F5.1, owner 2026-11-19): a job fill never clicks either -- not even an ordinary control
// (a radio, a drop-down, a pencil, a picker): Shopee's anti-bot answered the voucher fill's
// element.click() with /verify/traffic/error twice on 19/11. Every click is the person's.
describe("a job fill never clicks, focuses or dispatches a UI event (F5.1)", () => {
  const titleJob = rawJob("title", {
    open_path: "/portal/product/1001",
    fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 100, value: "Tên mới của sản phẩm mẫu" }],
  });
  const descriptionJob = rawJob("description_first_line", {
    open_path: "/portal/product/1001",
    fields: [{ key: "description_first_line", label: "Mô tả sản phẩm", mode: "first_line", max_chars: 500, value: "Dòng đầu mới của mô tả" }],
  });
  const productReadback = rawJob("readback", { mode: "readback", open_path: "/portal/product/1001", target: { item_id: "1001" }, datasets: ["item_catalog"] });
  const affiliateReadback = rawJob("readback", { mode: "readback", open_path: "/portal/web-seller-affiliate/open_campaign", target: { product_ids: ["2002"] }, datasets: ["item_catalog"] });
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
    ["a description", descriptionJob, "edit-eds-quill.html"],
    ["a page that is not the expected form", voucherJob(), "edit-unknown.html"],
    ["a title on the live eds layout", titleJob, "edit-eds-quill.html"],
    ["a voucher on the live eds layout", voucherJob(), "voucher-eds.html"],
    ["a combo on the live eds layout", comboJob(), "combo-eds.html"],
    ["an affiliate commission under Shopee's new-version notice", affiliateJob(), "affiliate-notice.html"],
    ["a product voucher on the live picker shapes", voucherJob({ usecase: 2, product_ids: ["1001"], smart: true, display: "code", starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", open_path: "/portal/marketing/vouchers/new?usecase=2" }), "voucher-live.html"],
    ["a combo on the live tier table", comboJob({ starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", product_ids: ["1001"] }), "combo-live.html"],
    ["a voucher's undo on the list", rawJob("voucher_end", { mode: "revert", open_path: "/portal/marketing/vouchers/list", code: "SHOPVGBB48" }), "voucher-list.html"],
    ["a combo's undo on the list", rawJob("combo_end", { mode: "revert", open_path: "/portal/marketing/bundle/list", name: "JC-2611-0009 V1" }), "bundle-list.html"],
    ["a product read-back", productReadback, "edit-eds-quill.html"],
    ["an affiliate read-back", affiliateReadback, "affiliate-live.html"],
  ])("%s", async (_name, raw, page) => {
    loadPage(page);
    const wire = wireEds(document, { datePicker: true });
    const hrefBefore = window.location.href;
    watch = watchForbidden();
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    const blur = vi.spyOn(HTMLElement.prototype, "blur");
    const h = jobHarness(raw);
    h.deps.postCurrent = async () => true;
    await runFillJob(h.deps);
    expect(watch.click).not.toHaveBeenCalled(); // 0 click calls
    expect(focus).not.toHaveBeenCalled();
    expect(blur).not.toHaveBeenCalled();
    expect(wire.clicks).toEqual([]);
    expect(wire.forbidden).toEqual([]);
    expect(watch.submit).not.toHaveBeenCalled();
    expect(watch.requestSubmit).not.toHaveBeenCalled();
    expect(watch.seen).toEqual([]); // no click / mouse / pointer / key / submit event reached the page
    for (const type of watch.dispatched) expect(["input", "change"]).toContain(type);
    expect(window.location.href).toBe(hrefBefore);
    for (const id of ["submit", "cancel", "budget-ok", "roas-ok", "comm-ok", "pconfirm", "save", "vend", "cdel"]) {
      expect(document.getElementById(id)?.getAttribute("data-juli-filled") ?? null).toBeNull();
      expect(document.getElementById(id)?.getAttribute("data-juli-guide") ?? null).toBeNull(); // never a step to press
    }
    focus.mockRestore();
    blur.mockRestore();
    wire.stop();
  });
});

describe("the source never presses anything", () => {
  const sources = import.meta.glob(["../src/core/fill/*.ts", "../src/core/jobs/*.ts", "../src/platforms/shopee/fill/*.ts", "../src/platforms/shopee/background/fill*.ts"], {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;
  const files = Object.entries(sources);
  const stripComments = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  it("covers every fill source file", () => {
    expect(files.map(([name]) => name.replace("../src/", "")).sort()).toEqual([
      "core/fill/form.ts",
      "core/fill/job-panel.ts",
      "core/fill/job-run.ts",
      "core/fill/locate.ts",
      "core/fill/log.ts",
      "core/fill/panel.ts",
      "core/fill/settle.ts",
      "core/fill/types.ts",
      "core/fill/verify.ts",
      "core/fill/write.ts",
      "core/jobs/fill-jobs.ts",
      "platforms/shopee/background/fill-jobs.ts",
      "platforms/shopee/background/fill.ts",
      "platforms/shopee/fill/controls.ts",
      "platforms/shopee/fill/fillers.ts",
      "platforms/shopee/fill/forms.ts",
      "platforms/shopee/fill/job-run.ts",
      "platforms/shopee/fill/job-types.ts",
      "platforms/shopee/fill/labels.ts",
      "platforms/shopee/fill/revert.ts",
      "platforms/shopee/fill/run.ts",
      "platforms/shopee/fill/saved.ts",
    ]);
  });

  // 0.3.28 (F5.1): no file presses anything any more (controls.ts included)
  it("has no .click() / .focus() / .blur() anywhere", () => {
    for (const [name, source] of files) expect(stripComments(source).match(/\.(click|focus|blur)\s*\(/g), name).toBeNull();
  });

  it.each(files)("%s", (name, source) => {
    const code = stripComments(source);
    const isControls = name.endsWith("shopee/fill/controls.ts");
    for (const banned of [
      /\.click\s*\(/,
      /\.(focus|blur)\s*\(/,
      /\.submit\s*\(/,
      /requestSubmit/,
      /new\s+(\w+\.)?(Mouse|Pointer|Keyboard|Touch|Focus|Wheel|Drag)Event/,
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

// 0.3.28 (F5.1b, owner 2026-11-19: "the Connector never clicks on Shopee"): the readers too. The
// order list's pager was the last .click() (order-dom.ts goToNextOrderPage); every Shopee source
// (readers, the page hooks, the content scripts, the background, the popup) is scanned, no
// exemption. TikTok's pack is out of scope.
describe("no Shopee source clicks, focuses or builds a UI event (F5.1b)", () => {
  const sources = import.meta.glob(["../src/platforms/shopee/**/*.ts", "../src/core/**/*.ts", "../src/background/*.ts"], {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;
  const stripComments = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  it("covers the readers and the page hooks", () => {
    const names = Object.keys(sources).map((n) => n.replace("../src/", ""));
    for (const must of ["platforms/shopee/order-dom.ts", "platforms/shopee/page/hook.ts", "platforms/shopee/page/market-hook.ts", "platforms/shopee/reader.ts", "platforms/shopee/reader-map.ts", "platforms/shopee/market.ts", "platforms/shopee/promotion-map.ts", "platforms/shopee/background/catchup.ts"]) {
      expect(names).toContain(must);
    }
  });

  it.each(Object.entries(sources))("%s", (name, source) => {
    const code = stripComments(source);
    for (const banned of [/\.(click|focus|blur)\s*\(/, /new\s+(\w+\.)?(Mouse|Pointer|Keyboard|Touch|Focus|Wheel|Drag)Event/, /dispatchEvent\([^)]*["'](click|mouse\w*|pointer\w*|key\w*|focus\w*)["']/]) {
      expect(code, `${name}: ${banned}`).not.toMatch(banned);
    }
  });
});
