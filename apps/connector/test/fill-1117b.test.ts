// @vitest-environment jsdom
// Connector 0.3.24 (batch-1117b X1): the live fill-only runs of 2026-11-17 failed on every fillable
// kind. Each case below reproduces a structure or timing seen on the real pages (synthetic text):
// - the description is a Quill editor: `.ql-editor` + the hidden `.ql-clipboard` under one label;
// - the title was written before Shopee loaded the product, which then overwrote it, and the panel
//   still said ✓ (and a page that never takes the write must say ✗ with what it shows);
// - the voucher / combo forms are drawn after the content script starts (0/10, 0/6 filled);
// - "Mã giảm giá thông minh" is gone from the voucher page; the combo tier rows have no label;
// - a full-page "new version" notice covers the affiliate page;
// - an untouched period stays "now": the panel must say so, the report carries period_ok: false;
// - every write keeps the value it replaced (before_values) for the revert.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { findControl, PANEL_ID } from "../src/core/fill/locate";
import { BANNER_JOB_NONE, BANNER_NO_PERIOD } from "../src/core/fill/job-panel";
import { PICK_NO_OPENER } from "../src/platforms/shopee/fill/controls";
import { runFillJob } from "../src/platforms/shopee/fill/job-run";
import { wireEds, type Wire } from "./eds-wire";
import { affiliateJob, comboJob, jobHarness, rawJob, voucherJob } from "./fill-job-helpers";
import { loadPage } from "./fill-helpers";

let wire: Wire;
beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
  wire = wireEds(document);
});
afterEach(() => wire.stop());

const NEW = "Tên mới của sản phẩm mẫu";
const OLD = "Tên cũ của sản phẩm mẫu";
const input = (id: string) => document.getElementById(id) as HTMLInputElement;
const panelText = () => document.getElementById(PANEL_ID)?.shadowRoot?.textContent ?? "";
const setByPage = (el: HTMLInputElement, value: string) => Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value);

const titleJob = () =>
  rawJob("title", {
    open_path: "/portal/product/1001",
    fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 100, value: NEW }],
  });
const descriptionJob = (value = "Dòng đầu mới, giao trong ngày") =>
  rawJob("description_first_line", {
    open_path: "/portal/product/1001",
    fields: [{ key: "description_first_line", label: "Mô tả sản phẩm", mode: "first_line", max_chars: 500, value }],
  });

describe("X1 locate: the real description editor (Quill)", () => {
  it("finds .ql-editor under the label, never the hidden .ql-clipboard", () => {
    loadPage("edit-eds-quill.html");
    expect(findControl(document, "Mô tả sản phẩm")?.id).toBe("editor");
  });

  it("drops a 0-wide helper when the real control is drawn with a box", () => {
    document.body.innerHTML = `<div class="row"><span>Mô tả sản phẩm</span>
      <div id="real" contenteditable="true"><p>a</p></div><div id="buffer" contenteditable="true"></div></div>`;
    const size = (id: string, w: number, h: number) => {
      const el = document.getElementById(id)!;
      Object.defineProperty(el, "offsetWidth", { value: w });
      Object.defineProperty(el, "offsetHeight", { value: h });
    };
    size("real", 675, 476);
    size("buffer", 0, 22);
    expect(findControl(document, "Mô tả sản phẩm")?.id).toBe("real");
  });

  it("fills the first line of the description through the job path; the rest and the clipboard stay", async () => {
    loadPage("edit-eds-quill.html");
    setByPage(input("title"), OLD);
    const h = jobHarness(descriptionJob(), { path: "/portal/product/1001" });
    expect(await runFillJob(h.deps)).toMatchObject({ status: "filled" });
    const editor = document.getElementById("editor")!;
    expect(Array.from(editor.children).map((c) => c.textContent)).toEqual(["Dòng đầu mới, giao trong ngày", "Dòng hai giữ nguyên", "Ý mộtÝ hai"]);
    expect(editor.querySelectorAll("li")).toHaveLength(2);
    expect(document.getElementById("clipboard")!.textContent).toBe("");
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled"]);
    expect(h.details.at(-1)?.before_values).toEqual({ first_line: "Dòng đầu cũ của mô tả" });
    expect(panelText()).toContain("Juli đã điền đủ");
    expect(wire.forbidden).toEqual([]);
  });
});

describe("X1 hydration and re-read: the title", () => {
  it("waits for Shopee to load the product before writing, so the load does not overwrite the title", async () => {
    loadPage("edit-eds-quill.html");
    const h = jobHarness(titleJob(), { path: "/portal/product/1001" });
    const sleep = h.deps.sleep;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (h.clock.t >= 2_000 && !input("title").dataset.loaded) {
        input("title").dataset.loaded = "1";
        setByPage(input("title"), OLD); // the product arrives and replaces whatever was typed
      }
    };
    expect(await runFillJob(h.deps)).toMatchObject({ status: "filled" });
    expect(input("title").value).toBe(NEW);
    expect(h.details.at(-1)?.before_values).toEqual({ title: OLD });
    expect(h.details.at(-1)?.fields).toEqual([{ key: "title", ok: true, seen: NEW }]);
  });

  it("says ✗ with what the page shows when the page never takes the write (no false ✓)", async () => {
    loadPage("edit-eds-quill.html");
    setByPage(input("title"), OLD);
    const h = jobHarness(titleJob(), { path: "/portal/product/1001" });
    const sleep = h.deps.sleep;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (input("title").value !== OLD) setByPage(input("title"), OLD); // the framework re-renders its own value
    };
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(input("title").value).toBe(OLD);
    expect(panelText()).toContain(BANNER_JOB_NONE);
    expect(panelText()).toContain(`✗ Tên sản phẩm: ${NEW}`);
    expect(panelText()).toContain(`Trang đang hiện «${OLD}»`);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "opened"]);
    expect(h.progress.at(-1)).toEqual({ filled: 0, total: 1 });
    expect(h.details.at(-1)?.fields).toEqual([{ key: "title", ok: false, seen: OLD }]);
  });

  it("turns ✓ into ✗ when the page puts its value back after the panel is up", async () => {
    loadPage("edit-eds-quill.html");
    setByPage(input("title"), OLD);
    const h = jobHarness(titleJob(), { path: "/portal/product/1001" });
    const sleep = h.deps.sleep;
    let shown = 0;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (document.getElementById(PANEL_ID) && (shown += 1) === 2) setByPage(input("title"), OLD);
    };
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(panelText()).toContain(`Trang đang hiện «${OLD}»`);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "opened"]);
  });
});

describe("X1 the voucher form on the real page", () => {
  /** The SPA draws the form 3 s after the content script starts. */
  const drawLate = (h: ReturnType<typeof jobHarness>, page = "voucher-eds.html", after?: () => void) => {
    document.body.innerHTML = `<div class="loading">Đang tải…</div>`;
    const sleep = h.deps.sleep;
    let drawn = false;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (!drawn && h.clock.t >= 3_000) {
        drawn = true;
        loadPage(page);
        after?.();
      }
    };
  };

  it("waits for the form, fills every field, and skips the gone 'Mã giảm giá thông minh'", async () => {
    const h = jobHarness(voucherJob());
    drawLate(h);
    expect(await runFillJob(h.deps)).toMatchObject({ status: "filled" });
    expect([input("name").value, input("code").value]).toEqual(["JC-2611-0007 V1 — voucher đơn tối thiểu", "GBB48"]);
    expect([input("start").value, input("end").value]).toEqual(["12:00 09-11-2026", "11:59 23-11-2026"]);
    expect([input("dvalue").value, input("minspend").value, input("total").value, input("perbuyer").value]).toEqual(["3000", "90000", "50", "1"]);
    expect(panelText()).toContain("Juli đã điền đủ");
    expect(panelText()).not.toContain("thông minh");
    expect(panelText()).not.toContain(BANNER_NO_PERIOD);
    const detail = h.details.at(-1)!;
    expect(detail.period_ok).toBe(true);
    expect(detail.before_values).toMatchObject({ name: "", starts_at: "15:43 17-11-2026", ends_at: "16:43 17-11-2026", per_buyer: "1", display: "Hiển thị nhiều nơi", voucher_type: "Khuyến Mãi" });
    expect(detail.fields.every((f) => f.ok)).toBe(true);
    expect(wire.forbidden).toEqual([]);
  });

  it("says 'Chưa điền thời gian — đừng bấm Xác nhận' and reports period_ok false when the period cannot be typed", async () => {
    const h = jobHarness(voucherJob());
    drawLate(h, "voucher-eds.html", () => {
      input("start").readOnly = true;
      input("end").readOnly = true;
    });
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(panelText()).toContain(BANNER_NO_PERIOD);
    expect(panelText()).toContain("Juli điền được 8/9 mục");
    expect(panelText()).toContain("✗ Thời gian");
    expect(input("start").value).toBe("15:43 17-11-2026");
    expect(h.details.at(-1)?.period_ok).toBe(false);
  });

  it("reports precisely when a product voucher's page has no product picker", async () => {
    const raw = voucherJob({ usecase: 2, product_ids: ["1001"], open_path: "/portal/marketing/vouchers/new?usecase=2" });
    const h = jobHarness(raw, { path: "/portal/marketing/vouchers/new" });
    drawLate(h);
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(panelText()).toContain(`✗ Sản phẩm: 0/1 đã tick — ${PICK_NO_OPENER}`);
  });
});

describe("X1 the combo form on the real page", () => {
  it("fills the unlabelled 'Mua [n] sản phẩm để được giảm [x] %GIẢM' rows and ticks the exact ids", async () => {
    loadPage("combo-eds.html");
    const h = jobHarness(comboJob());
    expect(await runFillJob(h.deps)).toMatchObject({ status: "filled" });
    const tiers = Array.from(document.querySelectorAll("#tiers .tier-row")).map((r) => Array.from(r.querySelectorAll("input")).map((i) => i.value));
    expect(tiers).toEqual([
      ["2", "5"],
      ["3", "8"],
    ]);
    const ticked = Array.from(document.querySelectorAll<HTMLInputElement>("#ptable input:checked")).map((i) => i.closest("tr")?.textContent);
    expect(ticked).toEqual(["Sản phẩm mẫu mộtID: 100112", "Sản phẩm mẫu baID: 10035"]);
    expect(h.details.at(-1)?.before_values).toMatchObject({ starts_at: "17:00 17-11-2026", tier1_qty: "", discount_type: "Giảm giá theo %" });
    expect(h.details.at(-1)?.period_ok).toBe(true);
    expect(wire.forbidden).toEqual([]);
  });

  it("says 'Juli chưa điền được mục nào' (not 'một phần') when nothing was filled", async () => {
    loadPage("edit-unknown.html");
    const h = jobHarness(comboJob());
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(panelText()).toContain(BANNER_JOB_NONE);
    expect(panelText()).toContain(BANNER_NO_PERIOD);
    expect(h.details.at(-1)?.period_ok).toBe(false);
  });
});

describe("X1 Shopee's 'new version' notice", () => {
  it("closes the notice by its close icon (never 'Khám phá Ngay', never a save), then fills", async () => {
    loadPage("affiliate-notice.html");
    const h = jobHarness(affiliateJob());
    expect(await runFillJob(h.deps)).toMatchObject({ status: "filled" });
    expect(document.getElementById("notice")).toBeNull();
    expect(input("pct").value).toBe("12.5");
    expect(wire.clicks).not.toContain("Khám phá Ngay");
    expect(wire.forbidden).toEqual([]);
    expect(panelText()).toContain("Juli đã đóng thông báo của Shopee «Phiên bản Chiến dịch Mở Rộng mới!");
    expect(h.details.at(-1)?.before_values).toEqual({ commission_pct: "" });
  });

  // 0.3.27 (owner, 2026-11-18): "Khám phá Ngay" navigates to the new campaign page; it is never a dismiss
  it("never presses 'Khám phá Ngay': a notice without a close icon is left and the panel says so", async () => {
    loadPage("affiliate-notice.html");
    document.querySelector(".eds-modal__close")?.remove();
    const h = jobHarness(affiliateJob());
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(wire.clicks).not.toContain("Khám phá Ngay");
    expect(document.getElementById("notice")).not.toBeNull();
    expect(panelText()).toContain("đang che trang; hãy tự đóng rồi mở lại từ Juli");
    expect(panelText().match(/đang che trang/g)).toHaveLength(1); // once (E21)
    expect(wire.forbidden).toEqual([]);
  });

  it("leaves a notice that only offers a confirm alone and says so", async () => {
    loadPage("affiliate-notice.html");
    document.querySelector(".eds-modal__close")?.remove();
    const button = document.querySelector<HTMLElement>("#notice button")!;
    button.textContent = "Đồng ý";
    button.setAttribute("data-forbidden", "");
    const h = jobHarness(affiliateJob());
    expect(await runFillJob(h.deps)).toMatchObject({ status: "partial" });
    expect(wire.forbidden).toEqual([]);
    expect(panelText()).toContain("đang che trang");
  });
});
