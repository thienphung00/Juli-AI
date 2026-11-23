// @vitest-environment jsdom
// batch-1123-a Track F (0.3.32): Chương Trình Của Shop, Flash Sale Của Shop, Deal Sốc, Ảnh bìa,
// Phân loại hàng and the end of their list rows. Fixtures are synthetic, built from the read-only
// captures of 23/11 (fasttrack-notes/2026-11-23/captures/f/01..04): class names as captured, no
// shop data. The Connector writes boxes only: HTMLElement.prototype.click stays at 0 calls.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FillLog } from "../src/core/fill/log";
import type { Env } from "../src/core/fill/form";
import { fillVariationPrices } from "../src/platforms/shopee/fill/fillers";
import { parseFillJob } from "../src/platforms/shopee/fill/job-types";
import { DEAL_STEP1_KEY, dealStep2Open, fillCover, fillDeal, fillFlashSale, fillProductDiscount, fillVariationSet, LOCK_KEY, LOCKED, priceLocked, slotShown, variationsLocked } from "../src/platforms/shopee/fill/promos";
import { fillProgrammeEnd, savedOn } from "../src/platforms/shopee/fill/revert";
import { rawJob } from "./fill-job-helpers";

let click: ReturnType<typeof vi.spyOn>;
let t = 0;
const env = (): Env => ({ doc: document, sleep: async (ms) => void (t += ms), now: () => t, log: new FillLog() });
const box = (sel: string) => document.querySelector<HTMLInputElement>(sel)!;
const guided = (el: Element | null) => el?.getAttribute("data-juli-guide") === "1";
beforeEach(() => {
  document.body.innerHTML = "";
  t = 0;
  // 23/11/2026 10:00 GMT+7: the flash slots below are 1-7 days ahead
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-23T03:00:00Z"));
  click = vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => {
  expect(click).not.toHaveBeenCalled();
  click.mockRestore();
  vi.useRealTimers();
});

// -- the jobs Juli serves -------------------------------------------------------------------

const discountJob = (over: Record<string, unknown> = {}) =>
  rawJob("product_discount", {
    open_path: "/portal/marketing/discount/create",
    name: "Sale cuối tháng",
    starts_at: "09:00 25-11-2026",
    ends_at: "21:00 28-11-2026",
    product_ids: ["1001"],
    variations: [
      { variation_id: "11", final_price: 90000, name: "Hộp 1" },
      { variation_id: "12", discount_pct: 12, name: "Hộp 3" },
    ],
    ...over,
  });
const flashJob = (over: Record<string, unknown> = {}) =>
  rawJob("flash_sale", {
    open_path: "/portal/marketing/shop-flash-sale/create",
    item_id: "1001",
    product_ids: ["1001"],
    slot: { day: "2026-11-30", label: "21:00:00 - 00:00:00", starts_at: "21:00 30-11-2026", hours: 3 },
    variations: [{ variation_id: "11", discount_pct: 20, name: "Hộp 1", stock: 50 }],
    units: 50,
    purchase_limit: 2,
    ...over,
  });
const dealJob = (over: Record<string, unknown> = {}) =>
  rawJob("add_on", {
    open_path: "/portal/marketing/add-on-deal/create",
    deal_type: "add_on",
    name: "Mua kèm tháng 12",
    starts_at: "00:00 25-11-2026",
    ends_at: "23:59 30-11-2026",
    main_product_ids: ["1001"],
    addon_product_ids: ["2001"],
    addons: [{ item_id: "2001", pct: 10, limit: 2 }],
    addon_limit: 2,
    ...over,
  });

describe("the new jobs parse only as Juli builds them", () => {
  it("accepts each kind and keeps its values", () => {
    const d = parseFillJob(discountJob());
    expect(d?.payload).toMatchObject({ kind: "product_discount", discount: { name: "Sale cuối tháng", variations: [{ variationId: "11", finalPrice: 90000 }, { variationId: "12", discountPct: 12 }] } });
    const f = parseFillJob(flashJob());
    expect(f?.payload).toMatchObject({ kind: "flash_sale", flash: { slot: { day: "2026-11-30", label: "21:00:00 - 00:00:00" }, purchaseLimit: 2 } });
    expect(parseFillJob(dealJob())?.payload).toMatchObject({ kind: "add_on", deal: { name: "Mua kèm tháng 12", addonLimit: 2, addons: [{ itemId: "2001", pct: 10, limit: 2 }] } });
    const gift = rawJob("gift", { open_path: "/portal/marketing/add-on-deal/create", deal_type: "gift", name: "Quà", starts_at: "00:00 25-11-2026", ends_at: "23:59 30-11-2026", min_spend: 300000, gift_qty: 2, gift_product_ids: ["3001"] });
    expect(parseFillJob(gift)?.payload).toMatchObject({ kind: "gift", deal: { minSpend: 300000, giftQty: 2 } });
    const cover = rawJob("cover_image", { open_path: "/portal/product/1001", item_id: "1001", old_cover_url: "https://cf.example.test/old.jpg" });
    expect(parseFillJob(cover)?.payload).toMatchObject({ kind: "cover_image", cover: { itemId: "1001" } });
    const set = rawJob("variation_set", { open_path: "/portal/product/1001", item_id: "1001", options: [{ name: "Set 3", price: 280000, sku: "S3", stock: 5 }], old_variations: [] });
    expect(parseFillJob(set)?.payload).toMatchObject({ kind: "variation_set", variations: { options: [{ name: "Set 3", price: 280000 }] } });
    const end = rawJob("flash_sale_end", { mode: "revert", open_path: "/portal/marketing/shop-flash-sale/list", slot: { day: "2026-11-30", label: "21:00:00 - 00:00:00" } });
    expect(parseFillJob(end)?.payload).toMatchObject({ kind: "flash_sale_end", end: { slot: { day: "2026-11-30" } } });
  });

  it("refuses what Shopee would refuse or what is not Juli's to guess", () => {
    expect(parseFillJob(dealJob({ name: "x".repeat(26) }))).toBeNull(); // Deal Sốc name: 25
    expect(parseFillJob(discountJob({ name: "x".repeat(151) }))).toBeNull(); // Chương Trình: 150
    expect(parseFillJob(flashJob({ slot: { day: "2026-11-30", label: "slot-7781", starts_at: "21:00 30-11-2026" } }))).toBeNull(); // never a slot id
    expect(parseFillJob(flashJob({ variations: [{ variation_id: "11", discount_pct: 3 }] }))).toBeNull(); // Shopee: 5-90 %
    // D4: only Shopee's 8 slot labels, and only tomorrow .. a week ahead
    expect(parseFillJob(flashJob({ slot: { day: "2026-11-30", label: "10:00:00 - 12:00:00", starts_at: "10:00 30-11-2026" } }))).toBeNull();
    expect(parseFillJob(flashJob({ slot: { day: "2026-11-23", label: "21:00:00 - 00:00:00", starts_at: "21:00 23-11-2026" } }))).toBeNull();
    expect(parseFillJob(flashJob({ slot: { day: "2026-12-01", label: "21:00:00 - 00:00:00", starts_at: "21:00 01-12-2026" } }))).toBeNull();
    expect(parseFillJob(flashJob({ slot: { day: "2026-11-24", label: "02:00:00 - 09:00:00", starts_at: "02:00 24-11-2026" } }))).not.toBeNull();
    // D2: the Deal Sốc undo opens the addondeal tab only
    expect(parseFillJob(rawJob("deal_end", { mode: "revert", open_path: "/portal/marketing/list/discount?discountType=all&status=all&page=1", name: "A" }))).toBeNull();
    expect(parseFillJob(discountJob({ all_pct: 10 }))).toBeNull(); // one % for all OR per variation
    expect(parseFillJob(discountJob({ variations: [{ variation_id: "11", final_price: 9, discount_pct: 9 }] }))).toBeNull();
    expect(parseFillJob(discountJob({ open_path: "/portal/marketing/discount/create?x=1" }))).toBeNull();
    expect(parseFillJob(rawJob("deal_end", { open_path: "/portal/marketing/list/discount", name: "A" }))).toBeNull(); // an end is a revert only
    expect(parseFillJob(rawJob("flash_sale", { ...flashJob().payload as object, mode: "revert" }))).toBeNull();
    expect(parseFillJob(rawJob("cover_image", { open_path: "/portal/product/1001", item_id: "1002", old_cover_url: "https://cf.example.test/o.jpg" }))).toBeNull(); // another item's page
  });
});

// -- Chương Trình Của Shop (capture 02) ---------------------------------------------------

const pairRow = (variation: string, nameClass: string, rowClass: string, extra = "") => `
  <div class="${rowClass}"><div class="${nameClass}">${variation}</div>
    <form class="eds-form form"><div class="price-discount-input">
      <div class="eds-input currency-input"><input type="text" value="100000"></div>
      <span>Hoặc</span><div class="eds-input discount-input"><input type="text" value="0"></div></div></form>${extra}</div>`;

const DISCOUNT_PAGE = `
  <div class="eds-form-item"><label>Tên chương trình khuyến mãi</label><div><input id="name" type="text" maxlength="150"></div></div>
  <div class="eds-form-item"><label>Thời gian khuyến mãi</label><div class="eds-date-picker"><input id="s" type="text" readonly value="10:30 23-11-2026"><input id="e" type="text" readonly value="11:30 23-11-2026"></div></div>
  <div class="eds-form-item"><label>Đồng bộ Chương trình khuyến mãi này sang Shop nước ngoài</label><div class="eds-switch eds-switch--open" id="sync"></div></div>
  <button type="button">Thêm sản phẩm</button>
  <table><tbody><tr><td>Mã: 1001</td></tr></tbody></table>
  ${pairRow("Hộp 1", "item-variation", "discount-edit-item-model-component")}
  ${pairRow("Hộp 3", "item-variation", "discount-edit-item-model-component")}`;

describe("Chương Trình Của Shop", () => {
  it("writes the name and one value per variation, guides the dates, never touches the sync switch", async () => {
    document.body.innerHTML = DISCOUNT_PAGE;
    const job = parseFillJob(discountJob())!;
    const out = await fillProductDiscount(env(), job.payload.kind === "product_discount" ? job.payload.discount : (null as never));
    expect(box("#name").value).toBe("Sale cuối tháng");
    const rows = document.querySelectorAll(".discount-edit-item-model-component");
    expect(rows[0]!.querySelector<HTMLInputElement>(".currency-input input")!.value).toBe("90000");
    expect(rows[1]!.querySelector<HTMLInputElement>(".discount-input input")!.value).toBe("12");
    expect(rows[1]!.querySelector<HTMLInputElement>(".currency-input input")!.value).toBe("100000"); // only one of the pair
    expect(out.steps.map((s) => s.label).join(" ")).not.toMatch(/Đồng bộ/);
    expect(document.getElementById("sync")!.getAttribute("data-juli-guide")).toBeNull();
    expect(out.steps.filter((s) => s.guide).map((s) => s.label).join(" ")).toMatch(/Chọn ngày bắt đầu 25\/11\/2026 09:00/);
  });
});

// -- Flash Sale Của Shop (capture 01) ---------------------------------------------------------

const FLASH_PAGE = `
  <button type="button">Lựa chọn khung giờ</button>
  <div class="eds-modal modal" hidden><table class="eds-table"><tr class="eds-table__row"><td><div class="slot"><label class="eds-radio"><input class="eds-radio__input" type="radio" value="9911"><span class="eds-radio__label">21:00:00 - 00:00:00</span></label></div></td></tr></table></div>
  <button type="button">Thêm sản phẩm</button>
  <div id="products"></div>`;
const FLASH_ROW = `<table><tbody><tr><td>Mã: 1001</td></tr></tbody></table>
  <div class="inner-row"><div class="eds-checkbox"></div><div class="variation">Hộp 1</div><div class="original-price">100000</div>
    <div class="discounted-price-discount"><div class="price-discount-input"><div class="eds-input currency-input"><input type="text" value="100000"></div><div class="eds-input discount-input"><input type="text" value="0"></div></div></div>
    <div class="campaign-stock"><div class="eds-input form-item"><input type="text" value="80"></div></div><div class="current-stock">80</div>
    <div class="purchase-limit"><div class="eds-input"><input type="text" placeholder="Không hạn mức"></div></div>
    <div class="enable-disable"><div class="eds-switch eds-switch--close" id="sw"></div></div></div>`;

describe("Flash Sale Của Shop", () => {
  it("guides the slot by day + label and writes price, stock and limit once the person's pick draws the row", async () => {
    document.body.innerHTML = FLASH_PAGE;
    const e = env();
    const job = parseFillJob(flashJob())!;
    const out = await fillFlashSale(e, job.payload.kind === "flash_sale" ? job.payload.flash : (null as never));
    expect(out.steps.find((s) => s.guide)!.label).toBe("Bấm «Lựa chọn khung giờ», chọn ngày 30/11/2026, khung «21:00:00 - 00:00:00», rồi Xác nhận của hộp chọn");
    expect(guided(document.querySelector("button"))).toBe(true);
    // the person picks the product: its variation row appears, Juli writes on the re-check
    document.getElementById("products")!.innerHTML = FLASH_ROW;
    e.log!.revealed();
    expect(box(".discount-input input").value).toBe("20");
    expect(box(".campaign-stock input").value).toBe("50");
    expect(box(".purchase-limit input").value).toBe("2");
    expect(guided(document.getElementById("sw"))).toBe(true); // the person turns it ON
    expect(slotShown("21:00 30-11-2026")).toBe("21:00 30/11/2026");
  });

  it("assumes the save lands on the Flash Sale list (E-case for the first run)", () => {
    const job = parseFillJob(flashJob())!;
    expect(savedOn(document, { pathname: "/portal/marketing/shop-flash-sale/list" }, job)).toBe(true);
    expect(savedOn(document, { pathname: "/portal/marketing/shop-flash-sale/create" }, job)).toBe(false);
  });
});

// -- Deal Sốc (capture 03) ------------------------------------------------------------------

const DEAL_STEP1 = `
  <div class="reset-item-content type-flex" id="t-addon">Mua Kèm Deal Sốc</div><div class="reset-item-content type-flex">Mua Để Nhận Quà</div>
  <div class="eds-form-item"><label>Tên chương trình</label><div><input id="name" type="text" placeholder="Nhập vào" maxlength="25"></div></div>
  <div class="eds-form-item"><label>Thời gian chương trình</label><div class="eds-date-picker"><input type="text" readonly value="10:30 23-11-2026"><input type="text" readonly value="11:30 23-11-2026"></div></div>
  <div class="eds-form-item"><label>Giới hạn sản phẩm mua kèm</label><div><input id="limit" type="text" placeholder="Số lượng tối đa: 100"></div></div>
  <button type="button">Lưu</button><div id="next"></div>`;
const DEAL_STEP3 = `<div><h3>Sản Phẩm Chính</h3><button type="button">Thêm sản phẩm</button></div>
  ${pairRow("Đỏ", "variation", "sub-edit-model inner-row", '<div class="purchase-limit"><div class="eds-input purchase-limit-input"><input type="text" placeholder="Không giới hạn"></div></div>')}`;

describe("Mua Kèm Deal Sốc", () => {
  it("fills step 1, says the person's step-1 Lưu, then writes the add-on % and limit on the re-check", async () => {
    document.body.innerHTML = DEAL_STEP1;
    const e = env();
    const job = parseFillJob(dealJob())!;
    const out = await fillDeal(e, job.payload.kind === "add_on" ? job.payload.deal : (null as never));
    expect(box("#name").value).toBe("Mua kèm tháng 12");
    expect(box("#limit").value).toBe("2");
    const step1 = out.steps.find((s) => s.keys?.includes(DEAL_STEP1_KEY))!;
    expect(step1.ok).toBe(false);
    expect(guided(Array.from(document.querySelectorAll("button")).find((b) => b.textContent === "Lưu")!)).toBe(false); // a save is never highlighted
    expect(e.log!.entries.get(DEAL_STEP1_KEY)!.ok()).toBe(false);
    // the person pressed Lưu: steps 2-3 open
    document.getElementById("next")!.innerHTML = DEAL_STEP3;
    expect(dealStep2Open(document)).toBe(true);
    expect(e.log!.entries.get(DEAL_STEP1_KEY)!.ok()).toBe(true);
    e.log!.revealed();
    expect(box(".sub-edit-model .discount-input input").value).toBe("10");
    expect(box(".purchase-limit-input input").value).toBe("2");
  });
});

// -- Phân loại hàng and Giá: locked by a promotion (probe 23/11) ------------------------------

describe("Phân loại hàng", () => {
  it("a greyed option box ends the job Bị khoá with nothing written", async () => {
    document.body.innerHTML = `<div>Vì chương trình khuyến mãi đang diễn ra, một số thông tin không được chỉnh sửa và bị tô xám.</div>
      <input placeholder="Nhập" value="Hộp 1"><input placeholder="Nhập" disabled>`;
    expect(variationsLocked(document)).toBe(true);
    const e = env();
    const out = await fillVariationSet(e, { itemId: "1001", options: [{ name: "Set 3", price: 280000 }], removeOptions: [], oldVariations: [] }, false);
    expect(out.steps).toEqual([{ label: "Phân loại hàng", ok: false, note: LOCKED, keys: [LOCK_KEY] }]);
    expect(e.log!.entries.get(LOCK_KEY)!.ok()).toBe(false);
    expect(Array.from(document.querySelectorAll("input")).map((i) => i.value)).toEqual(["Hộp 1", ""]);
  });

  it("a disabled Thêm nhóm phân loại is locked too", () => {
    document.body.innerHTML = `<button type="button" disabled>Thêm nhóm phân loại</button>`;
    expect(variationsLocked(document)).toBe(true);
  });

  it("unlocked: types only the option name into the empty Nhập box; the row's Giá / Kho hàng / SKU are guided (not captured)", async () => {
    document.body.innerHTML = `<input placeholder="Nhập" value="Hộp 1"><input placeholder="Nhập" id="empty"><table><tbody id="list"></tbody></table>`;
    const e = env();
    const out = await fillVariationSet(e, { itemId: "1001", options: [{ name: "Set 3", price: 280000, stock: 5, sku: "S3" }], removeOptions: [], oldVariations: [] }, false);
    expect(box("#empty").value).toBe("Set 3");
    expect(out.steps.find((s) => s.guide)).toMatchObject({ ok: false, label: "Nhập ở dòng «Set 3» của Danh sách phân loại hàng: Giá 280.000 ₫, Kho hàng 5, SKU phân loại S3" });
    document.getElementById("list")!.innerHTML = `<tr id="r"><td><span>Set 3</span></td><td><input type="text"></td><td><input type="text"></td><td><input type="text"></td></tr>`;
    e.log!.revealed();
    expect(Array.from(document.querySelectorAll<HTMLInputElement>("#list input")).map((i) => i.value)).toEqual(["", "", ""]);
    expect(guided(document.getElementById("r"))).toBe(true);
  });

  it("D6: a greyed box is never written, and the step shows ✗", async () => {
    document.body.innerHTML = FLASH_PAGE + FLASH_ROW;
    box(".campaign-stock input").disabled = true;
    const job = parseFillJob(flashJob())!;
    const out = await fillFlashSale(env(), job.payload.kind === "flash_sale" ? job.payload.flash : (null as never));
    expect(box(".campaign-stock input").value).toBe("80");
    expect(out.steps.find((s) => s.label.startsWith("SL sản phẩm khuyến mãi"))!.ok).toBe(false);
  });

  it("a price greyed by a promotion is detected before anything is written", async () => {
    document.body.innerHTML = `<div data-variation-id="11"><span>Hộp 1</span><input type="text" disabled value="100000"></div>`;
    expect(priceLocked(document, [{ variationId: "11" }])).toBe(true);
    document.body.innerHTML = `<div data-variation-id="11"><span>Hộp 1</span><input type="text" value="100000"></div>`;
    expect(priceLocked(document, [{ variationId: "11" }])).toBe(false);
    const out = await fillVariationPrices(env(), [{ variationId: "11", price: 95000 }]);
    expect(out.steps[0]!.keys).toEqual(["price_11"]); // a key Juli's report accepts
  });
});

// -- Ảnh bìa (probe 23/11: a synthetic file on the grid's box uploads) -----------------------

const grid = (n: number) => `<div class="shopee-image-manager">${Array.from({ length: n }, () => '<div class="shopee-image-manager__itembox can-drag"><img></div>').join("")}
  <div class="eds-upload-wrapper eds-upload-dragger"><input type="file" accept="image/*" multiple id="file"></div></div>`;

describe("Ảnh bìa", () => {
  it("without an image source the person downloads the new cover; dragging it first is always theirs", async () => {
    document.body.innerHTML = grid(3);
    const out = await fillCover(env(), { itemId: "1001", oldCoverUrl: "https://cf.example.test/old.jpg", newCoverUrl: "https://img.example.test/new.png" }, false);
    expect(out.steps.map((s) => s.label)).toEqual(["Tải ảnh bìa mới từ thẻ Juli, rồi bấm «Thêm hình ảnh»", "Kéo ảnh mới lên vị trí đầu (Ảnh bìa)"]);
  });

  it("with a source the image goes on the grid's file box; 9 images first asks to delete one", async () => {
    const files: unknown[] = [];
    class FakeDataTransfer {
      private list: File[] = [];
      items = { add: (f: File) => this.list.push(f) };
      get files() {
        return this.list as unknown as FileList;
      }
    }
    vi.stubGlobal("DataTransfer", FakeDataTransfer);
    document.body.innerHTML = grid(3);
    const input = box("#file");
    Object.defineProperty(input, "files", { set: (v) => files.push(v), configurable: true });
    const source = vi.fn(async () => new Blob(["x"], { type: "image/png" }));
    const out = await fillCover(env(), { itemId: "1001", oldCoverUrl: "https://cf.example.test/old.jpg", newCoverUrl: "https://img.example.test/new.png" }, false, source);
    expect(source).toHaveBeenCalledWith("https://img.example.test/new.png");
    expect(files).toHaveLength(1);
    expect(out.steps[0]!.label).toBe("Tải ảnh bìa mới lên lưới ảnh");
    document.body.innerHTML = grid(9);
    const full = await fillCover(env(), { itemId: "1001", oldCoverUrl: "https://cf.example.test/old.jpg" }, true, source);
    expect(full.steps[0]!.label).toMatch(/đủ 9 ảnh: xoá 1 ảnh/);
    vi.unstubAllGlobals();
  });
});

// -- the undo of a programme: the list row's Thêm › Kết thúc (capture 03) ----------------------

describe("ending a programme row", () => {
  it("highlights Thêm, then the menu's Kết thúc once the person opens it; presses nothing", async () => {
    document.body.innerHTML = `<table><tbody>
      <tr><td><span>Mua kèm tháng 12</span></td><td><span>Đang diễn ra</span></td><td><button type="button">Chỉnh sửa</button><button type="button" id="more">Thêm</button></td></tr>
      <tr><td><span>Khác</span></td><td><button type="button">Thêm</button></td></tr></tbody></table><div id="menu"></div>`;
    const e = env();
    const job = parseFillJob(rawJob("deal_end", { mode: "revert", open_path: "/portal/marketing/list/discount?discountType=addondeal&status=all&page=1", name: "Mua kèm tháng 12", deal_type: "add_on" }))!;
    const out = await fillProgrammeEnd(e, job);
    expect(out.steps[0]).toMatchObject({ ok: true, label: "Dòng của Deal Sốc Mua kèm tháng 12: nút «Thêm» đã được tô hồng" });
    expect(guided(document.getElementById("more"))).toBe(true);
    document.getElementById("menu")!.innerHTML = `<ul class="eds-dropdown"><li role="menuitem">Đơn hàng</li><li role="menuitem" id="end">Kết thúc</li></ul>`;
    e.log!.revealed();
    expect(guided(document.getElementById("end"))).toBe(true);
  });
});
