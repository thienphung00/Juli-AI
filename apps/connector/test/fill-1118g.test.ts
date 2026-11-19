// @vitest-environment jsdom
// Connector 0.3.27 (batch-1118g, track t1): F2.1–F2.6, F3.1, F3.2 and contract D. The fixtures are
// SYNTHETIC; their structure follows the read-only captures of 2026-11-18 (date-time picker, combo
// tiers + product picker, affiliate open campaign) and, where nothing was captured, the closest
// Shopee eds shapes (voucher list, bundle list, the affiliate rate editor and pager).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BANNER_NO_PERIOD, BANNER_SAVED } from "../src/core/fill/job-panel";
import { FillLog } from "../src/core/fill/log";
import { verifyWrites } from "../src/core/fill/verify";
import { PANEL_ID } from "../src/core/fill/locate";
import { FORBIDDEN_PRESS, unsafePress } from "../src/platforms/shopee/fill/controls";
import { SMART_MISSING } from "../src/platforms/shopee/fill/fillers";
import { runFillJob } from "../src/platforms/shopee/fill/job-run";
import { parseFillJob } from "../src/platforms/shopee/fill/job-types";
import { END_MARK, END_TODO } from "../src/platforms/shopee/fill/revert";
import { wireEds, type Wire } from "./eds-wire";
import { afterPanel, affiliateJob, choose, comboJob, JOB_ID, jobHarness, personClicks, rawJob, voucherJob } from "./fill-job-helpers";
import { loadPage } from "./fill-helpers";

let wire: Wire;
beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
  document.querySelectorAll(".eds-react-date-picker__popup,.eds-react-select-options-list").forEach((p) => p.remove());
  wire = wireEds(document, { datePicker: true });
  click = vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => {
  wire.stop();
  // 0.3.28 (F5.1): the Connector never clicks (the person's clicks here are dispatched events)
  expect(click).not.toHaveBeenCalled();
  click.mockRestore();
});
let click: ReturnType<typeof vi.spyOn>;
/** The person / Shopee's React picker writes a value (native setter + input / change). */
const typed = (el: HTMLInputElement, v: string) => {
  setByPage(el, v);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
};
/** voucher-live.html as Shopee draws it, product already listed: a card that matches it needs no click. */
const listed = (into: string) => {
  document.getElementById(into)!.innerHTML = "<tr><td>Sản phẩm mẫu một</td><td>Mã: 1001</td></tr>";
};
const asDrawn = { smart: false, display: "multi", starts_at: "19:57 18-11-2026", ends_at: "20:57 18-11-2026" };

const input = (id: string) => document.getElementById(id) as HTMLInputElement;
const panelText = () => document.getElementById(PANEL_ID)?.shadowRoot?.querySelector(".box")?.textContent ?? "";
const setByPage = (el: HTMLInputElement, value: string) => Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value);

const productVoucher = (over: Record<string, unknown> = {}) =>
  voucherJob({
    usecase: 2,
    product_ids: ["1001"],
    display: "code",
    smart: true,
    starts_at: "00:00 01-03-2027",
    ends_at: "23:59 02-03-2027",
    discount: { type: "amount", value: 5000 },
    min_spend: 100000,
    open_path: "/portal/marketing/vouchers/new?usecase=2",
    ...over,
  });
const harnessFor = (raw: Record<string, unknown>) => jobHarness(raw, { path: String(raw.open_path).split("?")[0] });

describe("F2.1 the date-time picker", () => {
  it("the date-time picker is the person's: two numbered steps with the dates; ✓ and period_ok once the picker shows them", async () => {
    loadPage("voucher-live.html");
    const h = harnessFor(productVoucher());
    let first = "";
    afterPanel(h, () => {
      first = panelText();
      typed(input("start"), "00:00 01-03-2027");
      typed(input("end"), "23:59 02-03-2027");
    });
    await runFillJob(h.deps);
    expect(first).toContain("1. Chọn ngày bắt đầu 01/03/2027 00:00");
    expect(first).toContain("2. Chọn ngày kết thúc 02/03/2027 23:59");
    expect(first).toContain(BANNER_NO_PERIOD);
    expect(document.querySelector(".eds-react-date-picker__popup")).toBeNull(); // never opened by Juli
    const detail = h.details.filter(Boolean).at(-1)!;
    expect(detail.period_ok).toBe(true);
    expect(detail.fields.filter((f) => f.key === "starts_at" || f.key === "ends_at")).toEqual([
      { key: "starts_at", ok: true, seen: "00:00 01-03-2027" },
      { key: "ends_at", ok: true, seen: "23:59 02-03-2027" },
    ]);
    expect(detail.before_values).toMatchObject({ starts_at: "19:57 18-11-2026", ends_at: "20:57 18-11-2026" });
    expect(panelText()).not.toContain(BANNER_NO_PERIOD);
    expect(wire.clicks).toEqual([]);
    expect(wire.forbidden).toEqual([]); // the form's Xác nhận / Hủy never
  });

  it("does not pick a past (disabled) day: the period stays ✗ and the panel says do not save", async () => {
    loadPage("voucher-live.html");
    const h = harnessFor(productVoucher({ starts_at: "00:00 01-11-2026", ends_at: "23:59 02-11-2026" }));
    await runFillJob(h.deps);
    expect(input("start").value).toBe("19:57 18-11-2026");
    expect(panelText()).toContain(BANNER_NO_PERIOD);
    expect(h.details.find((d) => d !== undefined)?.period_ok).toBe(false);
    expect(wire.forbidden).toEqual([]);
  });

  it("never highlights a confirm: neither the pickers' own Xác nhận nor the form's is a step to press", async () => {
    loadPage("voucher-live.html");
    await runFillJob(harnessFor(productVoucher()).deps);
    for (const id of ["submit", "pconfirm-live", "cancel"]) expect(document.getElementById(id)!.getAttribute("data-juli-guide")).toBeNull();
    expect(document.querySelector("[data-opens='#picker']")!.getAttribute("data-juli-guide")).toBe("1");
    expect(wire.clicks).toEqual([]);
  });
});

describe("F2.2 the voucher form", () => {
  it("product voucher: the amount written; smart on, 'Chia sẻ qua mã voucher' and the product are the person's; every field read back non-empty", async () => {
    loadPage("voucher-live.html");
    const h = harnessFor(productVoucher());
    afterPanel(h, () => {
      typed(input("start"), "00:00 01-03-2027");
      typed(input("end"), "23:59 02-03-2027");
      document.getElementById("smart")!.setAttribute("aria-checked", "true");
      choose(document.querySelector('input[name="disp"][value="code"]'));
      listed("chosen"); // the person's picker Xác nhận
    });
    await runFillJob(h.deps);
    expect(input("dvalue").value).toBe("5000");
    expect(h.reports.map((r) => r[1])).toContain("filled");
    const detail = h.details.filter(Boolean).at(-1)!;
    expect(detail.fields.every((f) => f.ok && f.seen.trim() !== "")).toBe(true);
    expect(detail.fields.find((f) => f.key === "display")).toEqual({ key: "display", ok: true, seen: "Chia sẻ thông qua mã Voucher" });
    expect(wire.forbidden).toEqual([]);
  });

  it("keeps the smart switch off when the card does not ask for it", async () => {
    loadPage("voucher-live.html");
    const h = harnessFor(productVoucher({ smart: undefined }));
    await runFillJob(h.deps);
    expect(document.getElementById("smart")!.getAttribute("aria-checked")).toBe("false");
    expect(panelText()).toContain("✓ Mã giảm giá thông minh: tắt");
  });

  it("says ✗ when the card wants the smart voucher and the page has no such switch", async () => {
    loadPage("voucher-live.html");
    document.getElementById("smart")!.closest(".eds-form-item")!.remove();
    const h = harnessFor(productVoucher());
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(panelText()).toContain(`✗ Mã giảm giá thông minh: bật — ${SMART_MISSING}`);
  });

  it("an empty read is never ok (E45: display read '' counted as ok)", async () => {
    const log = new FillLog();
    const el = document.createElement("div");
    document.body.append(el);
    log.wrote({ key: "display", el, want: "Chia sẻ thông qua mã Voucher", seen: () => "", ok: () => true });
    const clock = { t: 0 };
    const checks = await verifyWrites({ doc: document, sleep: async (ms) => void (clock.t += ms), now: () => clock.t, log }, log);
    expect(checks).toEqual([{ key: "display", ok: false, seen: "" }]);
  });

  it("parses the card's smart flag and refuses a non-boolean", () => {
    expect(parseFillJob(productVoucher())).toMatchObject({ payload: { voucher: { smart: true, usecase: 2, productIds: ["1001"] } } });
    expect(parseFillJob(voucherJob())).toMatchObject({ payload: { voucher: { smart: false } } });
    expect(parseFillJob(productVoucher({ smart: "yes" }))).toBeNull();
  });
});

describe("F2.3 the new voucher's id after the person's save", () => {
  it("sees the redirect to the list, says 'Đã lưu — bấm Đã làm', and reports captured with the id from the row's edit link", async () => {
    loadPage("voucher-live.html");
    listed("chosen");
    const h = harnessFor(productVoucher(asDrawn));
    const sleep = h.deps.sleep;
    let swapped = false;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (!swapped && h.reports.some((r) => r[1] === "filled") && h.clock.t > 60_000) {
        swapped = true; // the person pressed Shopee's Xác nhận: Seller Centre shows the list
        loadPage("voucher-list.html");
        h.deps.loc.pathname = "/portal/marketing/vouchers/list";
      }
    };
    await runFillJob(h.deps);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled", "saved", "captured"]);
    expect(h.refs.at(-1)).toBe("7700000000000001");
    expect(panelText()).toContain(BANNER_SAVED);
    expect(wire.forbidden).toEqual([]);
  });
});

describe("F2.4 the combo form (live shape)", () => {
  it("writes tier 1 and the order limit; the person adds tier 2 (Juli writes it), sets the period and picks the product", async () => {
    loadPage("combo-live.html");
    const h = harnessFor(comboJob({ starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", product_ids: ["1001"], purchase_limit: 1 }));
    afterPanel(h, () => {
      personClicks(document.querySelector("[data-add-row]"));
      typed(input("start"), "00:00 01-03-2027");
      typed(input("end"), "23:59 02-03-2027");
      listed("combo-products");
    });
    await runFillJob(h.deps);
    const rows = Array.from(document.querySelectorAll("#tiers tr")).map((tr) => Array.from(tr.querySelectorAll("input")).map((i) => i.value));
    expect(rows).toEqual([
      ["2", "5"],
      ["3", "8"],
    ]);
    expect(input("limit").value).toBe("1");
    const detail = h.details.filter(Boolean).at(-1)!;
    expect(detail.fields.map((f) => [f.key, f.ok])).toEqual(expect.arrayContaining([["tier1_qty", true], ["tier1_value", true], ["tier2_qty", true], ["tier2_value", true], ["purchase_limit", true], ["product_ids", true]]));
    expect(detail.fields.every((f) => f.ok)).toBe(true);
    expect(h.reports.map((r) => r[1])).toContain("filled");
    expect(wire.forbidden).toEqual([]);
  });

  it("the picker's search gets the id once the person opens it (the search type is the person's: «tìm theo Mã sản phẩm»)", async () => {
    loadPage("combo-live.html");
    const h = harnessFor(comboJob({ starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", product_ids: ["1001"] }));
    afterPanel(h, () => document.getElementById("picker")!.removeAttribute("hidden"));
    await runFillJob(h.deps);
    expect(input("psearch").value).toBe("1001");
    expect(panelText()).toContain("tìm theo Mã sản phẩm 1001");
    expect(document.getElementById("combo-products")!.textContent).toBe("");
  });
});

describe("F2.5 the affiliate open campaign (live shape)", () => {
  it("the person closes the notice (never 'Explore Now'), goes to page 2 and opens the row's rate; Juli writes the rate and keeps the old one", async () => {
    loadPage("affiliate-live.html");
    const h = jobHarness(affiliateJob({ product_ids: ["2002"], commission_pct: 12 }));
    h.deps.postCurrent = async () => true;
    afterPanel(h, () => {
      personClicks(document.querySelector("#notice [aria-label='close']"));
      document.getElementById("notice")!.remove();
      personClicks(document.querySelector("[data-next-page]"));
      personClicks(document.querySelectorAll("[data-opens='#rate-pop']")[1]!);
    });
    await runFillJob(h.deps);
    expect(input("rate").value).toBe("12");
    const detail = h.details.filter(Boolean).at(-1)!;
    expect(detail.before_values.commission_pct).toBe("9");
    expect(detail.fields.find((f) => f.key === "commission_pct")).toEqual({ key: "commission_pct", ok: true, seen: "12" });
    expect(h.reports.map((r) => r[1])).toContain("filled");
    expect(wire.clicks).not.toContain("Explore Now");
    expect(wire.forbidden).toEqual([]); // Save / Remove / Explore Now never
  });

  it("names the id the person must find (Juli never pages)", async () => {
    loadPage("affiliate-live.html");
    const h = jobHarness(affiliateJob({ product_ids: ["2999"], commission_pct: 12 }));
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(panelText()).toContain("Tìm ID 2999");
    expect(wire.forbidden).toEqual([]);
  });
});

describe("E46: the saved report carries the person's hand edits", () => {
  it("Juli types, the person changes a field by hand, the save redirects: saved carries the hand-edited value", async () => {
    loadPage("voucher-live.html");
    listed("chosen");
    const h = harnessFor(productVoucher(asDrawn));
    const sleep = h.deps.sleep;
    let step = 0;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (step === 0 && h.reports.some((r) => r[1] === "filled")) {
        step = 1; // the person lowers the minimum by hand (E43/E46)
        setByPage(input("minspend"), "90000");
        h.clock.t += 0;
      } else if (step === 1 && h.clock.t > 200_000) {
        step = 2; // Shopee's Xác nhận: the list replaces the form
        loadPage("voucher-list.html");
        h.deps.loc.pathname = "/portal/marketing/vouchers/list";
      }
    };
    await runFillJob(h.deps);
    const at = h.reports.findIndex((r) => r[1] === "saved");
    expect(at).toBeGreaterThan(0);
    const saved = h.details[at]!;
    expect(saved.fields.find((f) => f.key === "min_spend")).toEqual({ key: "min_spend", ok: false, seen: "90000" });
    expect(saved.fields.find((f) => f.key === "name")?.ok).toBe(true); // what still held the card's value
    expect(h.progress[at]).toMatchObject({ total: expect.any(Number) });
    expect(h.progress[at]!.filled).toBeLessThan(h.progress[at]!.total);
  });
});

describe("F2.6 the panel follows the page", () => {
  it("re-checks after the person fixes a field by hand (debounced) and reports filled", async () => {
    loadPage("voucher-live.html");
    document.querySelector(".eds-date-picker")!.setAttribute("data-no-picker", "1"); // the picker does not open
    listed("chosen");
    const h = harnessFor(productVoucher({ ...asDrawn, starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027" }));
    const sleep = h.deps.sleep;
    let fixed = false;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (!fixed && h.reports.some((r) => r[1] === "opened" && h.progress[h.reports.indexOf(r)] !== undefined)) {
        fixed = true; // the person picks the dates by hand
        setByPage(input("start"), "00:00 01-03-2027");
        setByPage(input("end"), "23:59 02-03-2027");
      }
    };
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "opened", "filled"]);
    expect(h.details.at(-1)?.period_ok).toBe(true);
    expect(panelText()).toContain("Juli đã điền đủ");
    expect(panelText()).not.toContain(BANNER_NO_PERIOD);
  });

  it("after Shopee's 'Đăng tải thành công' the panel says 'Đã lưu — bấm Đã làm trong Juli' (E10)", async () => {
    loadPage("edit-eds-quill.html");
    const raw = rawJob("title", { open_path: "/portal/product/1001", fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 120, value: "Tên mới của sản phẩm mẫu" }] });
    const h = jobHarness(raw);
    const sleep = h.deps.sleep;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (h.reports.some((r) => r[1] === "filled") && !document.querySelector(".toast")) {
        document.body.insertAdjacentHTML("beforeend", `<div class="eds-react-toast">Đăng tải thành công</div>`);
      }
    };
    await runFillJob(h.deps);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled", "saved"]);
    expect(panelText()).toContain(BANNER_SAVED);
  });

  it("shows Shopee's feedback widget as no notice at all (E21)", async () => {
    loadPage("edit-eds-quill.html");
    document.body.insertAdjacentHTML("beforeend", `<div class="feedback-modal" role="dialog">Thông tin góp ý · Quay màn hình khi gặp sự cố · Phiên bản mới</div>`);
    const raw = rawJob("title", { open_path: "/portal/product/1001", fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 120, value: "Tên mới của sản phẩm mẫu" }] });
    await runFillJob(jobHarness(raw).deps);
    expect(panelText()).not.toContain("Thông báo của Shopee");
  });
});

describe("F3.1 revert jobs (contract B)", () => {
  it("a text revert fills the old value with the same fill_check", async () => {
    loadPage("edit-eds-quill.html");
    const raw = rawJob("title", {
      mode: "revert",
      open_path: "/portal/product/1001",
      fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 120, value: "Tên cũ của sản phẩm mẫu" }],
    });
    expect(parseFillJob(raw)).toMatchObject({ kind: "title", mode: "revert" });
    const h = jobHarness(raw);
    expect(await runFillJob(h.deps)).toMatchObject({ status: "filled" });
    expect(h.details.find((d) => d)!.fields).toEqual([{ key: "title", ok: true, seen: "Tên cũ của sản phẩm mẫu" }]);
    expect(panelText()).toContain("Đây là hoàn tác");
  });

  const voucherEnd = (over: Record<string, unknown> = {}) =>
    rawJob("voucher_end", { mode: "revert", open_path: "/portal/marketing/vouchers/list", voucher_id: "7700000000000001", code: "SHOPVGBB48", name: "JC-2611-0007 V1 — voucher đơn tối thiểu", ...over });

  it("voucher_end: finds the row by id, highlights its Kết thúc (never presses it), reports filled; saved once the row shows ended", async () => {
    loadPage("voucher-list.html");
    const h = jobHarness(voucherEnd());
    const sleep = h.deps.sleep;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (h.reports.some((r) => r[1] === "filled") && document.getElementById("vend")) {
        // the person pressed Kết thúc and confirmed Shopee's dialog
        document.getElementById("vstatus")!.textContent = "Đã kết thúc";
        document.getElementById("vend")!.remove();
      }
    };
    await runFillJob(h.deps);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled", "saved"]);
    expect(wire.forbidden).toEqual([]);
    expect(panelText()).toContain(BANNER_SAVED);
  });

  it("voucher_end: the highlighted control is the row's own Kết thúc", async () => {
    loadPage("voucher-list.html");
    const h = jobHarness(voucherEnd({ voucher_id: undefined }));
    h.deps.sleep = async (ms) => {
      h.clock.t += ms * 1000; // end the follow at once
    };
    await runFillJob(h.deps);
    expect(document.getElementById("vend")!.getAttribute(END_MARK)).toBe("1");
    expect(document.querySelectorAll(`[${END_MARK}]`)).toHaveLength(1);
    expect(panelText()).toContain(END_TODO);
    expect(wire.clicks).toEqual([]);
  });

  it("combo_end: by name on the bundle list, Xóa highlighted, saved once Shopee says it was deleted", async () => {
    loadPage("bundle-list.html");
    const raw = rawJob("combo_end", { mode: "revert", open_path: "/portal/marketing/bundle/list", name: "JC-2611-0009 V1" });
    const h = jobHarness(raw);
    const sleep = h.deps.sleep;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (h.reports.some((r) => r[1] === "filled") && document.getElementById("crow")) {
        document.getElementById("crow")!.remove();
        document.body.insertAdjacentHTML("beforeend", `<div class="eds-react-toast">Xóa thành công</div>`);
      }
    };
    await runFillJob(h.deps);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled", "saved"]);
    expect(wire.forbidden).toEqual([]);
  });

  it.each([
    ["combo_end", "bundle-list.html", "crow", { open_path: "/portal/marketing/bundle/list", name: "JC-2611-0009 V1" }],
    ["voucher_end", "voucher-list.html", "vactions", { open_path: "/portal/marketing/vouchers/list", voucher_id: "7700000000000001" }],
  ])("%s: a row that only vanishes (another tab, filter or page) is NOT ended: the job stays filled", async (kind, page, id, payload) => {
    loadPage(page);
    const h = jobHarness(rawJob(kind, { mode: "revert", ...payload }));
    const sleep = h.deps.sleep;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (h.reports.some((r) => r[1] === "filled")) document.getElementById(id)?.closest("tr")?.remove();
    };
    await runFillJob(h.deps);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled"]);
  });

  it("parses end jobs only as reverts, and refuses a revert of a kind that cannot be one", () => {
    expect(parseFillJob(voucherEnd())).toMatchObject({ kind: "voucher_end", mode: "revert", payload: { end: { id: "7700000000000001", code: "SHOPVGBB48" } } });
    expect(parseFillJob(voucherEnd({ mode: undefined }))).toBeNull();
    expect(parseFillJob(voucherEnd({ open_path: "/portal/marketing/vouchers/new" }))).toBeNull();
    expect(parseFillJob(voucherEnd({ voucher_id: "x1", code: undefined, name: undefined }))).toBeNull();
    expect(parseFillJob(voucherJob({ mode: "revert" }))).toBeNull();
    expect(parseFillJob(affiliateJob({ mode: "revert" }))).toMatchObject({ mode: "revert" });
  });
});

describe("F3.2 read-back of a product (contract C) and its current values (contract D)", () => {
  const readback = (over: Record<string, unknown> = {}) =>
    rawJob("readback", { mode: "readback", open_path: "/portal/product/1001", target: { item_id: "1001" }, datasets: ["item_catalog"], ...over });

  it("reads the saved title and first line, posts them, reports captured, types nothing", async () => {
    loadPage("edit-eds-quill.html");
    input("title").value = "Tên đã lưu của sản phẩm mẫu";
    const posted: unknown[] = [];
    const h = jobHarness(readback());
    h.deps.postCurrent = async (rows) => {
      posted.push(...rows);
      return true;
    };
    const before = document.body.innerHTML;
    await runFillJob(h.deps);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "captured"]);
    expect(posted).toHaveLength(1);
    expect(posted[0]).toEqual({ item_id: "1001", item_name: "Tên đã lưu của sản phẩm mẫu", description_first_line: "Dòng đầu cũ của mô tả" });
    expect(document.body.innerHTML).toBe(before);
    expect(wire.clicks).toEqual([]);
  });

  it("reports failed / readback_post_failed when what it read did not reach Juli", async () => {
    loadPage("edit-eds-quill.html");
    input("title").value = "Tên đã lưu của sản phẩm mẫu";
    const h = jobHarness(readback());
    h.deps.postCurrent = async () => false;
    await runFillJob(h.deps);
    expect(h.reports.map((r) => [r[1], r[2]])).toEqual([
      ["opened", undefined],
      ["failed", "readback_post_failed"],
    ]);
  });

  it("parses read-backs strictly", () => {
    expect(parseFillJob(readback())).toMatchObject({ kind: "readback", mode: "readback", payload: { readback: { target: { itemId: "1001" }, datasets: ["item_catalog"] } } });
    expect(parseFillJob(readback({ mode: undefined }))).toBeNull();
    expect(parseFillJob(readback({ datasets: ["orders"] }))).toBeNull();
    expect(parseFillJob(readback({ target: { item_id: "1002" } }))).toBeNull(); // not this page's item
    expect(parseFillJob(readback({ open_path: "/portal/marketing/vouchers/list", target: { voucher_id: "77" }, datasets: ["voucher_list"] }))).toMatchObject({ kind: "readback" });
    expect(parseFillJob(readback({ open_path: "/portal/marketing/vouchers/new", target: { voucher_id: "77" }, datasets: ["voucher_list"] }))).toBeNull();
  });

  it("a title fill posts what Shopee held before Juli typed (contract D: item_name, description_first_line)", async () => {
    loadPage("edit-eds-quill.html");
    const posted: { item_id: string; item_name?: string; description_first_line?: string }[] = [];
    const raw = rawJob("title", { open_path: "/portal/product/1001", fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 120, value: "Tên mới của sản phẩm mẫu" }] });
    const h = jobHarness(raw);
    h.deps.postCurrent = async (rows) => {
      posted.push(...rows);
      return true;
    };
    input("title").value = "Tên cũ của sản phẩm mẫu";
    await runFillJob(h.deps);
    expect(input("title").value).toBe("Tên mới của sản phẩm mẫu");
    expect(posted).toEqual([{ item_id: "1001", item_name: "Tên cũ của sản phẩm mẫu", description_first_line: "Dòng đầu cũ của mô tả" }]);
  });
});

describe("Shopee's anti-bot page (2026-11-18)", () => {
  it("a job page that IS the traffic check reports failed / shopee_traffic_check and types nothing", async () => {
    loadPage("edit-eds-quill.html");
    const h = jobHarness(rawJob("title", { open_path: "/portal/product/1001", fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 120, value: "Tên mới" }] }));
    window.history.replaceState(null, "", "/verify/traffic/error");
    try {
      expect(await runFillJob(h.deps)).toEqual({ status: "blocked", reason: "shopee_traffic_check" });
      expect(h.reports).toEqual([[JOB_ID, "failed", "shopee_traffic_check"]]);
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });
});

describe("t2's job shapes (2026-11-18)", () => {
  it("voucher_end with code_suffix only: the row whose code ENDS with it (no prefix assumed), Kết thúc highlighted", async () => {
    loadPage("voucher-list.html");
    const raw = rawJob("voucher_end", { mode: "revert", open_path: "/portal/marketing/vouchers/list", voucher_id: null, code_suffix: "GBB48", name: "không khớp" });
    expect(parseFillJob(raw)).toMatchObject({ payload: { end: { code: "GBB48" } } });
    const h = jobHarness(raw);
    h.deps.sleep = async (ms) => void (h.clock.t += ms * 1000);
    await runFillJob(h.deps);
    expect(document.getElementById("vend")!.getAttribute(END_MARK)).toBe("1");
    expect(wire.forbidden).toEqual([]);
  });

  it("an affiliate read-back never clicks: under the notice / on another page it posts nothing and fails readback_not_found", async () => {
    loadPage("affiliate-live.html");
    const raw = rawJob("readback", { mode: "readback", open_path: "/portal/web-seller-affiliate/open_campaign", target: { product_ids: ["2002"] }, datasets: ["item_catalog"] });
    expect(parseFillJob(raw)).toMatchObject({ kind: "readback", payload: { readback: { target: { productIds: ["2002"] } } } });
    const h = jobHarness(raw);
    h.deps.postCurrent = async () => true;
    await runFillJob(h.deps);
    expect(h.reports).toEqual([
      [JOB_ID, "opened", undefined],
      [JOB_ID, "failed", "readback_not_found"],
    ]);
    expect(document.getElementById("notice")).not.toBeNull();
    expect(wire.clicks).toEqual([]);
  });

  it("an affiliate read-back reads the rates the page shows, posts them, reports captured", async () => {
    loadPage("affiliate-live.html");
    personClicks(document.querySelector("#notice [aria-label='close']")); // the person closed it earlier
    document.getElementById("notice")!.remove();
    const raw = rawJob("readback", { mode: "readback", open_path: "/portal/web-seller-affiliate/open_campaign", target: { product_ids: ["2001"] }, datasets: ["item_catalog"] });
    const posted: unknown[] = [];
    const h = jobHarness(raw);
    h.deps.postCurrent = async (rows) => {
      posted.push(...rows);
      return true;
    };
    await runFillJob(h.deps);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "captured"]);
    expect(posted).toEqual(expect.arrayContaining([{ item_id: "2001", commission_pct: 13 }]));
    expect(input("rate").value).toBe("");
    expect(wire.forbidden).toEqual([]);
  });
});

describe("hardening: the texts never named a step to press", () => {
  it.each(["Kết thúc", "Remove", "Khám phá ngay", "Explore Now", "OK", "Xóa", "Xoá", "End"])("names «%s» unsafe", (text) => {
    expect(FORBIDDEN_PRESS.test(text.toLocaleLowerCase("vi"))).toBe(true);
    document.body.innerHTML = `<button type="button" data-forbidden>${text}</button>`;
    expect(unsafePress(document.querySelector("button")!)).not.toBeNull();
    expect(wire.forbidden).toEqual([]);
  });
});
