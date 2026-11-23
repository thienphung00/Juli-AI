// batch-1123-a F (Connector 0.3.32): the fills of Chương Trình Của Shop, Flash Sale Của Shop, Mua
// Kèm Deal Sốc / Mua Để Nhận Quà, Ảnh bìa and Phân loại hàng, and the end of their list rows.
//
// The 0.3.28 rule holds: the Connector writes text / number boxes (and, for a new cover, the image
// grid's own file box) and never clicks. Every click is a numbered, highlighted step for the
// person; Shopee's Xác nhận / Lưu / Cập nhật / Kết thúc stay the person's. Selectors come from the
// read-only captures of 23/11 (fasttrack-notes/2026-11-23/captures/f/01..04): the shared
// `.price-discount-input` pair (Giá sau giảm / Giá đã giảm / Giá Mua Kèm OR %GIẢM) is one filler
// for the three programme forms. Rows a person's click reveals (the products they pick) are
// written on the next re-check.

import { normalizeLabel } from "../../../core/fill/locate";
import { keyed } from "../../../core/fill/log";
import type { FillOutcome, Step } from "../../../core/fill/form";
import { buttonsMatching, controlWithText, type Env, findPressable, findRow, highlight, pickProducts, setRowText, textBoxesIn, writeBox } from "./controls";
import { type Add, dong, GUIDED_TODO, NEVER_CLICKS, PERIOD_KEYS, period, picked, stepper, variationPriceRow, writeOrLater } from "./fillers";
import type { CoverPayload, DealPayload, DiscountRow, EndTarget, FillJob, FlashSalePayload, ProductDiscountPayload, VariationSetPayload } from "./job-types";

// -- the shared price / percent pair ---------------------------------------------------------

const PAIR = '[class*="price-discount-input"]';
const PRICE_BOX = `${PAIR} [class*="currency-input"] input`;
const PCT_BOX = `${PAIR} [class*="discount-input"] input`;

/** A report key Juli accepts (`^[a-z][a-z0-9_]{0,39}$`): prefix + the id's letters / digits. */
export function fk(prefix: string, id: string | number, part?: number): string {
  const tail = String(id).toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 24);
  return `${prefix}_${tail}${part !== undefined ? `_${part}` : ""}`.slice(0, 40);
}

const shown = (el: Element) => !el.closest("[hidden],[aria-hidden='true']");
const leafText = (el: Element | null) => normalizeLabel(el?.textContent ?? "");

/** The variation rows of a programme form (outside dialogs), each with the text of its variation cell. */
export function variationRows(doc: Document, rowSel: string, nameSel: string): { row: HTMLElement; name: string }[] {
  return Array.from(doc.querySelectorAll<HTMLElement>(rowSel))
    .filter((r) => shown(r) && !r.closest('[role="dialog"],[class*="modal"]') && !!r.querySelector(PAIR))
    .map((row) => ({ row, name: leafText(row.querySelector(nameSel)) }));
}

/** The row of one variation: by its unique name, else the only row when the card names one variation. */
function rowOf(rows: { row: HTMLElement; name: string }[], v: { name?: string }, single: boolean): HTMLElement | null {
  if (v.name) {
    const hits = rows.filter((r) => r.name === normalizeLabel(v.name!));
    return hits.length === 1 ? hits[0]!.row : null;
  }
  return single && rows.length === 1 ? rows[0]!.row : null;
}

const valueText = (v: { finalPrice?: number; discountPct?: number }) => (v.finalPrice !== undefined ? dong(v.finalPrice) : `${v.discountPct}%`);

/** Writes Giá … OR %GIẢM of one row (one box only: Shopee fills the other itself). */
export function writePair(env: Env, row: Element, v: { finalPrice?: number; discountPct?: number }, key: string): boolean {
  const box = row.querySelector<HTMLInputElement>(v.finalPrice !== undefined ? PRICE_BOX : PCT_BOX);
  if (!box || box.disabled || box.readOnly) return false;
  return writeBox(keyed(env, key), box, String(v.finalPrice ?? v.discountPct));
}

/** Each variation's value, now or once the person's product pick draws its row. */
function fillRows(env: Env, add: Add, rows: () => { row: HTMLElement; name: string }[], list: readonly DiscountRow[], what: string, extra?: (row: HTMLElement, v: DiscountRow) => void): void {
  for (const v of list) {
    const key = fk("value", v.variationId);
    const find = () => rowOf(rows(), v, list.length === 1);
    const now = find();
    const label = `${what} · ${v.name ?? v.variationId}: ${valueText(v)}`;
    if (now) {
      add(label, writePair(env, now, v, key), { keys: [key] });
      extra?.(now, v);
      continue;
    }
    env.log?.later({
      key,
      write: () => {
        const r = find();
        if (!r) return false;
        writePair(env, r, v, key);
        extra?.(r, v);
        return true;
      },
    });
    add(label, false, { keys: [key], note: v.name ? "Juli điền khi dòng của phân loại này hiện ra." : "Phân loại trùng tên: điền tay theo thẻ." });
  }
}

/** A guided step only described (no control to highlight safely, or not captured yet). */
const say = (add: Add, text: string, key?: string) => add(text, false, { guide: true, ...(key ? { keys: [key] } : {}) });

// -- Chương Trình Của Shop (product_discount) ------------------------------------------------

export const DISCOUNT_LABELS = { name: "Tên chương trình khuyến mãi", period: "Thời gian khuyến mãi", products: "Thêm sản phẩm" } as const;
const DISCOUNT_ROW = '[class*="discount-edit-item-model-component"]';
const DISCOUNT_NAME = '[class*="item-variation"]';

export async function fillProductDiscount(env: Env, d: ProductDiscountPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  add(`Tên chương trình: ${d.name}`, setRowText(keyed(env, "name"), DISCOUNT_LABELS.name, d.name), { keys: ["name"] });
  period(env, add, DISCOUNT_LABELS.period, d.startsAt, d.endsAt);
  picked(add, pickProducts(keyed(env, "product_ids"), DISCOUNT_LABELS.products, d.productIds), DISCOUNT_LABELS.products, d.productIds);
  const rows = () => variationRows(env.doc, DISCOUNT_ROW, DISCOUNT_NAME);
  if (d.allPct !== undefined) {
    // one % for every variation row the person's pick drew
    const key = "all_pct";
    const writeAll = () => {
      const all = rows();
      for (const [i, r] of all.entries()) writePair(env, r.row, { discountPct: d.allPct! }, `${key}_${i}`);
      return all.length > 0;
    };
    if (!writeAll()) env.log?.later({ key, write: writeAll });
    add(`Giảm ${d.allPct}% cho mọi phân loại`, rows().length > 0, { keys: rows().map((_, i) => `${key}_${i}`) });
  } else fillRows(env, add, rows, d.variations, "Giá sau giảm / %GIẢM");
  if (d.promoQty !== undefined) say(add, `Chọn «${d.promoQty}» ở «Số lượng sản phẩm khuyến mãi» (Thiết lập hàng loạt)`);
  if (d.perBuyerLimit !== undefined) say(add, `Chọn «${d.perBuyerLimit}» ở «Giới hạn mua tối đa của mỗi khách hàng»`);
  return { steps, todo: [GUIDED_TODO, "Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo chương trình."], notes: [NEVER_CLICKS], periodKeys: PERIOD_KEYS };
}

// -- Flash Sale Của Shop ---------------------------------------------------------------------

export const FLASH_SLOT_TEXT = /^\s*lựa chọn khung giờ\s*$/i;
export const ADD_GROUP_TEXT = /thêm nhóm phân loại/i;
export const FLASH_LABELS = { slot: "Lựa chọn khung giờ", modal: "Chọn khung giờ Flash sale Của Shop", products: "Thêm sản phẩm" } as const;
const FLASH_ROW = '[class*="inner-row"]';
const FLASH_NAME = '[class*="variation"]:not([class*="inner-row"])';

/** "21:00 30/11/2026" as the form shows the chosen slot. */
export function slotShown(startsAt: string): string {
  const p = /^(\d{2}:\d{2}) (\d{2})-(\d{2})-(\d{4})$/.exec(startsAt);
  return p ? `${p[1]} ${p[2]}/${p[3]}/${p[4]}` : startsAt;
}

const dayText = (iso: string) => iso.split("-").reverse().join("/");
const switchOn = (sw: Element) => !/eds-switch--close/.test(sw.className.toString());

export async function fillFlashSale(env: Env, f: FlashSalePayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  // the slot: the person picks the day and Shopee's slot label, by text (never a stored slot id)
  const wanted = slotShown(f.slot.startsAt);
  const chosen = () => (env.doc.body.textContent ?? "").includes(wanted);
  env.log?.wrote({ key: "slot", el: env.doc.body, want: wanted, seen: () => (chosen() ? wanted : "chưa chọn"), ok: chosen });
  if (chosen()) add(`Khung giờ: ${wanted}`, true, { keys: ["slot"] });
  else {
    const open = findPressable(env, FLASH_LABELS.slot);
    if (open) highlight(open);
    env.log?.later({
      key: "slot_mark",
      write: () => {
        const label = Array.from(env.doc.querySelectorAll<HTMLElement>('[class*="eds-radio__label"]')).find((l) => normalizeLabel(l.textContent ?? "") === normalizeLabel(f.slot.label));
        if (label) highlight((label.closest("label") as HTMLElement | null) ?? label);
        return !!label;
      },
    });
    add(`Bấm «${FLASH_LABELS.slot}», chọn ngày ${dayText(f.slot.day)}, khung «${f.slot.label}», rồi Xác nhận của hộp chọn`, false, { keys: ["slot"], guide: true });
  }
  picked(add, pickProducts(keyed(env, "product_ids"), FLASH_LABELS.products, f.productIds), FLASH_LABELS.products, f.productIds);
  const rows = () => variationRows(env.doc, FLASH_ROW, FLASH_NAME);
  const extra = (row: HTMLElement, v: DiscountRow) => {
    if (v.stock !== undefined) {
      const box = row.querySelector<HTMLInputElement>('[class*="campaign-stock"] input');
      if (box) writeBox(keyed(env, fk("stock", v.variationId)), box, String(v.stock));
    }
    if (f.purchaseLimit !== undefined) {
      const box = row.querySelector<HTMLInputElement>('[class*="purchase-limit"] input');
      if (box) writeBox(keyed(env, fk("limit", v.variationId)), box, String(f.purchaseLimit));
    }
    const sw = row.querySelector<HTMLElement>('[class*="enable-disable"] [class*="eds-switch"]');
    if (sw) {
      env.log?.wrote({ key: fk("on", v.variationId), el: sw, want: "bật", seen: () => (switchOn(sw) ? "bật" : "tắt"), ok: () => switchOn(sw) });
      if (!switchOn(sw)) highlight(sw);
    }
  };
  fillRows(env, add, rows, f.variations, "Giá đã giảm / %GIẢM", extra);
  for (const v of f.variations) {
    if (v.stock !== undefined) add(`SL sản phẩm khuyến mãi · ${v.name ?? v.variationId}: ${v.stock}`, false, { keys: [fk("stock", v.variationId)] });
    if (f.purchaseLimit !== undefined) add(`Giới hạn đặt hàng · ${v.name ?? v.variationId}: ${f.purchaseLimit}`, false, { keys: [fk("limit", v.variationId)] });
    add(`Bật công tắc của phân loại ${v.name ?? v.variationId}`, false, { keys: [fk("on", v.variationId)], guide: true });
  }
  if (f.variations.every((v) => v.stock === undefined)) say(add, `Chia SL sản phẩm khuyến mãi (tổng ${f.units}) cho các phân loại`);
  return { steps, todo: [GUIDED_TODO, "Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo Flash Sale."], notes: [NEVER_CLICKS] };
}

// -- Mua Kèm Deal Sốc / Mua Để Nhận Quà ------------------------------------------------------

export const DEAL_LABELS = {
  type: { add_on: "Mua Kèm Deal Sốc", gift: "Mua Để Nhận Quà" },
  name: { add_on: ["Tên chương trình", "Tên Deal Sốc"], gift: ["Tên chương trình Mua để nhận quà", "Tên chương trình"] },
  period: ["Thời gian chương trình", "Thời gian bắt đầu/kết thúc", "Thời gian"],
  limit: "Giới hạn sản phẩm mua kèm",
  gift: "Điều kiện nhận quà",
  step2: "Sản Phẩm Chính",
} as const;
/** The Connector's check that step 1 was saved (the backend reads it: an abandoned job = an empty programme on Shopee). */
export const DEAL_STEP1_KEY = "step1_saved";
export const DEAL_STEP1 = "Bấm Lưu ở bước 1 (Shopee tạo chương trình, rồi mở bước 2–3)";
const ADDON_ROW = '[class*="sub-edit-model"][class*="inner-row"]';

/** Step 2 is open: its heading and a product picker opener are on the page. */
export function dealStep2Open(doc: Document): boolean {
  const heads = Array.from(doc.querySelectorAll("*")).filter((el) => el.children.length === 0 && normalizeLabel(el.textContent ?? "") === normalizeLabel(DEAL_LABELS.step2));
  return heads.some(shown) && buttonsMatching(doc, /thêm sản phẩm/i).length > 0;
}

function firstRow(env: Env, labels: readonly string[]): string | null {
  return labels.find((l) => !!findRow(env.doc, l)) ?? null;
}

export async function fillDeal(env: Env, d: DealPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  const type = DEAL_LABELS.type[d.dealType];
  // the type card: ✓ once the form shows the type's own field
  const own = d.dealType === "add_on" ? DEAL_LABELS.limit : DEAL_LABELS.gift;
  const typed = () => !!findRow(env.doc, own);
  env.log?.wrote({ key: "deal_type", el: env.doc.body, want: type, seen: () => (typed() ? type : "loại khác"), ok: typed });
  if (typed()) add(`Loại Deal Sốc: ${type}`, true, { keys: ["deal_type"] });
  else {
    const card = Array.from(env.doc.querySelectorAll<HTMLElement>('[class*="type-flex"],[class*="reset-item-content"]')).find((c) => normalizeLabel(c.textContent ?? "").includes(normalizeLabel(type)));
    if (card) highlight(card);
    add(`Chọn thẻ «${type}» ở «Loại Deal Sốc»`, false, { keys: ["deal_type"], guide: true });
  }
  const nameLabel = firstRow(env, DEAL_LABELS.name[d.dealType]);
  add(`Tên chương trình: ${d.name}`, !!nameLabel && setRowText(keyed(env, "name"), nameLabel, d.name), { keys: ["name"], ...(nameLabel ? {} : { note: "Không thấy ô tên; nhập tay." }) });
  const periodLabel = firstRow(env, DEAL_LABELS.period);
  if (periodLabel) period(env, add, periodLabel, d.startsAt, d.endsAt);
  else say(add, `Chọn thời gian ${d.startsAt} → ${d.endsAt}`);
  if (d.dealType === "add_on" && d.addonLimit !== undefined) {
    const limit = d.addonLimit;
    const find = () => {
      const row = findRow(env.doc, DEAL_LABELS.limit);
      return row ? textBoxesIn(row)[0] : undefined;
    };
    add(`Giới hạn sản phẩm mua kèm: ${limit}`, writeOrLater(env, "addon_limit", find, String(limit)), { keys: ["addon_limit"] });
  }
  if (d.dealType === "gift") {
    const boxes = () => {
      const row = findRow(env.doc, DEAL_LABELS.gift);
      return row ? textBoxesIn(row) : [];
    };
    add(`Mua ${dong(d.minSpend!)} để nhận ${d.giftQty} quà`, writeOrLater(env, "min_spend", () => boxes()[0], String(d.minSpend)) && writeOrLater(env, "gift_qty", () => boxes()[1], String(d.giftQty)), { keys: ["min_spend", "gift_qty"] });
  }
  // the person's step-1 save creates the programme on Shopee: Juli only says it (never highlights a save)
  const open = () => dealStep2Open(env.doc);
  env.log?.wrote({ key: DEAL_STEP1_KEY, el: env.doc.body, want: "đã lưu", seen: () => (open() ? "đã lưu" : "chưa"), ok: open });
  add(DEAL_STEP1, open(), { keys: [DEAL_STEP1_KEY], guide: true });
  const main = d.dealType === "add_on" ? d.mainProductIds : d.mainProductIds;
  if (main.length > 0) say(add, `Bước 2: «Thêm sản phẩm» chính, Mã sản phẩm ${main.join(", ")}`);
  const second = d.dealType === "add_on" ? d.addonProductIds : d.giftProductIds;
  say(add, `Bước 3: «Thêm sản phẩm» ${d.dealType === "add_on" ? "mua kèm" : "quà tặng"}, Mã sản phẩm ${second.join(", ")}`);
  if (d.dealType === "add_on" && d.addons.length > 0) addonValues(env, add, d);
  return { steps, todo: [GUIDED_TODO, "Sau bước 3, kiểm tra lại rồi bấm Xác nhận / Lưu của Shopee."], notes: [NEVER_CLICKS], periodKeys: PERIOD_KEYS };
}

/**
 * Step 3's Giá Mua Kèm OR % and Giới hạn đặt hàng (capture 03, edit mode). The rows name only the
 * variation, not the product, so Juli writes them only when every add-on carries the same value
 * (one add-on, or the same % / price for all); otherwise each row is the person's.
 */
function addonValues(env: Env, add: Add, d: DealPayload): void {
  const first = d.addons[0]!;
  const same = d.addons.every((a) => a.price === first.price && a.pct === first.pct && a.limit === first.limit);
  const text = first.price !== undefined ? `Giá Mua Kèm ${dong(first.price)}` : `Giảm ${first.pct}%`;
  if (!same) {
    say(add, `Nhập Giá Mua Kèm / % cho từng sản phẩm mua kèm theo thẻ`);
    return;
  }
  const writeAll = () => {
    const rows = Array.from(env.doc.querySelectorAll<HTMLElement>(ADDON_ROW)).filter(shown);
    for (const [i, row] of rows.entries()) {
      writePair(env, row, { ...(first.price !== undefined ? { finalPrice: first.price } : { discountPct: first.pct! }) }, fk("addon", i));
      const box = row.querySelector<HTMLInputElement>('[class*="purchase-limit-input"] input');
      if (first.limit !== undefined && box) writeBox(keyed(env, fk("addon_limit", i)), box, String(first.limit));
    }
    return rows.length > 0;
  };
  if (!writeAll()) env.log?.later({ key: "addon_values", write: writeAll });
  add(`Bước 3: ${text}${first.limit !== undefined ? `, giới hạn ${first.limit}/đơn` : ""} cho mọi phân loại mua kèm`, false, { keys: [fk("addon", 0)] });
}

// -- Ảnh bìa (product page) ------------------------------------------------------------------

export const COVER_MAX_IMAGES = 9;
export const COVER_DOWNLOAD = "Tải ảnh bìa mới từ thẻ Juli";
export const COVER_DRAG = "Kéo ảnh mới lên vị trí đầu (Ảnh bìa)";
const ITEMBOX = '[class*="shopee-image-manager__itembox"]';

/** The main (1:1) image grid: the first image manager on the page, and its file box. */
export function imageGrid(doc: Document): { grid: HTMLElement; file: HTMLInputElement | null; count: number } | null {
  const grid = doc.querySelector<HTMLElement>('[class*="shopee-image-manager"]:not([class*="__"])');
  if (!grid) return null;
  const file = (grid.querySelector<HTMLInputElement>('input[type="file"]') ?? grid.parentElement?.querySelector<HTMLInputElement>('input[type="file"]')) || null;
  return { grid, file, count: grid.querySelectorAll(ITEMBOX).length };
}

/** Where a new cover's bytes come from. Fill sources never touch the network (fill-never-clicks):
 * the caller passes a source; without one the person downloads the image (a guided step). */
export type ImageSource = (url: string) => Promise<Blob | null>;

/** Puts an image on the grid's own file box (a value write: probe 23/11 shows Shopee uploads it, appended last). */
export function putImage(env: Env, file: HTMLInputElement, blob: Blob): boolean {
  const win = env.doc.defaultView as (Window & typeof globalThis) | null;
  if (!win || typeof win.DataTransfer !== "function" || !/^image\//.test(blob.type)) return false;
  const dt = new win.DataTransfer();
  dt.items.add(new win.File([blob], `juli-cover.${blob.type.split("/")[1] ?? "png"}`, { type: blob.type }));
  file.files = dt.files;
  file.dispatchEvent(new win.Event("change", { bubbles: true }));
  return true;
}

export async function fillCover(env: Env, c: CoverPayload, revert: boolean, source?: ImageSource): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  const grid = imageGrid(env.doc);
  if (!grid) return { steps: [{ label: "Hình ảnh sản phẩm", ok: false, note: "Không thấy lưới ảnh trên trang" }], todo: [], notes: [NEVER_CLICKS] };
  const start = grid.count;
  if (start >= COVER_MAX_IMAGES) {
    const room = () => (imageGrid(env.doc)?.count ?? COVER_MAX_IMAGES) < COVER_MAX_IMAGES;
    env.log?.wrote({ key: "room", el: grid.grid, want: "còn chỗ", seen: () => (room() ? "còn chỗ" : "đủ 9 ảnh"), ok: room });
    add("Sản phẩm đã đủ 9 ảnh: xoá 1 ảnh (không phải ảnh bìa) trước", false, { keys: ["room"], guide: true });
  }
  const url = revert ? c.oldCoverUrl : c.newCoverUrl;
  const added = () => (imageGrid(env.doc)?.count ?? 0) > start - (start >= COVER_MAX_IMAGES ? 1 : 0);
  env.log?.wrote({ key: "upload", el: grid.grid, want: "đã thêm", seen: () => (added() ? "đã thêm" : "chưa"), ok: added });
  const blob = url && source && start < COVER_MAX_IMAGES && grid.file ? await source(url).catch(() => null) : null;
  const sent = !!blob && putImage(env, grid.file!, blob);
  if (sent) add(revert ? "Tải lại ảnh bìa cũ lên lưới ảnh" : "Tải ảnh bìa mới lên lưới ảnh", added(), { keys: ["upload"] });
  else if (revert) add(`Tải ảnh bìa cũ (${c.oldCoverUrl}) về máy, rồi bấm «Thêm hình ảnh»`, false, { keys: ["upload"], guide: true });
  else add(`${COVER_DOWNLOAD}, rồi bấm «Thêm hình ảnh»`, false, { keys: ["upload"], guide: true });
  add(COVER_DRAG, false, { guide: true });
  return {
    steps,
    todo: [GUIDED_TODO, "Kiểm tra ảnh đầu tiên có nhãn «Ảnh bìa», rồi bấm Cập nhật của Shopee. Rời trang bằng nút Hủy của Shopee."],
    notes: [NEVER_CLICKS],
  };
}

// -- Phân loại hàng (product page) -----------------------------------------------------------

export const LOCKED = "Bị khoá vì chương trình khuyến mãi đang chạy";
export const LOCK_KEY = "promotion_lock";
const LOCK_BANNER = /bị tô xám/i;

/** Probe 23/11: a running promotion greys the options ("Nhập" disabled, "Thêm nhóm phân loại" disabled, the banner). */
export function variationsLocked(doc: Document): boolean {
  if (doc.querySelector('input[placeholder="Nhập"][disabled]')) return true;
  const addGroup = buttonsMatching(doc, ADD_GROUP_TEXT)[0];
  if (addGroup && (addGroup.disabled || /disabled/.test(addGroup.className.toString()))) return true;
  return Array.from(doc.querySelectorAll<HTMLElement>("div,span,p")).some((el) => el.children.length === 0 && shown(el) && LOCK_BANNER.test(el.textContent ?? ""));
}

/** The whole job is refused, nothing written: the backend reads the lock check and fails the job. */
export function lockedOutcome(env: Env, what: string): FillOutcome {
  env.log?.wrote({ key: LOCK_KEY, el: env.doc.body, want: "mở", seen: () => LOCKED, ok: () => false });
  return { steps: [{ label: what, ok: false, note: LOCKED, keys: [LOCK_KEY] }], todo: [], notes: [NEVER_CLICKS] };
}

/** A price row of the card whose box is greyed (disabled) and has no box left to type in. */
export function priceLocked(doc: Document, variations: readonly { variationId: string; name?: string }[]): boolean {
  return variations.some((v) => {
    const row = variationPriceRow(doc, v.variationId, v.name) ?? lockedNamedRow(doc, v.name);
    return !!row && textBoxesIn(row).length === 0 && !!row.querySelector("input[disabled]");
  });
}

/** variationPriceRow skips rows without a usable box: find a greyed one by its unique name. */
function lockedNamedRow(doc: Document, name?: string): HTMLElement | null {
  if (!name) return null;
  const wanted = normalizeLabel(name);
  const rows = Array.from(doc.querySelectorAll<HTMLElement>("tr,[class*='table-row']")).filter((r) => r.querySelector("input[disabled]") && Array.from(r.querySelectorAll("*")).some((el) => el.children.length === 0 && normalizeLabel(el.textContent ?? "") === wanted));
  return rows.length === 1 ? rows[0]! : null;
}

const optionBoxes = (doc: Document) => Array.from(doc.querySelectorAll<HTMLInputElement>('input[placeholder="Nhập"]')).filter((i) => shown(i) && !i.disabled && !i.readOnly);

/** The row of the "Danh sách phân loại hàng" table that shows this option's name. */
function optionRow(doc: Document, name: string): HTMLElement | null {
  const wanted = normalizeLabel(name);
  const rows = Array.from(doc.querySelectorAll<HTMLElement>("tr,[class*='table-row']")).filter((r) => shown(r) && Array.from(r.querySelectorAll("*")).some((el) => el.children.length === 0 && normalizeLabel(el.textContent ?? "") === wanted));
  const inner = rows.filter((r) => !rows.some((o) => o !== r && r.contains(o)));
  return inner.length === 1 ? (inner[0] as HTMLElement) : null;
}

/** Giá / Kho hàng / SKU phân loại of one option row, in the table's column order (capture 04). */
function writeOptionRow(env: Env, row: HTMLElement, o: { name: string; price?: number; stock?: number; sku?: string }, key: string): boolean {
  const boxes = textBoxesIn(row).filter((b) => normalizeLabel(b.value) !== normalizeLabel(o.name));
  const values = [o.price, o.stock, o.sku];
  let ok = true;
  values.forEach((v, i) => {
    if (v === undefined || !boxes[i]) return;
    ok = writeBox(keyed(env, `${key}_${i}`), boxes[i]!, String(v)) && ok;
  });
  return ok;
}

export async function fillVariationSet(env: Env, v: VariationSetPayload, revert: boolean): Promise<FillOutcome> {
  if (variationsLocked(env.doc)) return lockedOutcome(env, "Phân loại hàng");
  const steps: Step[] = [];
  const add = stepper(steps);
  if (revert) {
    for (const name of v.removeOptions) {
      const holder = Array.from(env.doc.querySelectorAll<HTMLInputElement>('input[placeholder="Nhập"]')).find((i) => normalizeLabel(i.value) === normalizeLabel(name));
      if (holder) highlight((holder.closest('[class*="item"],[class*="option"]') as HTMLElement | null) ?? holder);
      const gone = () => !Array.from(env.doc.querySelectorAll<HTMLInputElement>('input[placeholder="Nhập"]')).some((i) => normalizeLabel(i.value) === normalizeLabel(name));
      env.log?.wrote({ key: fk("remove", name), el: env.doc.body, want: "đã xoá", seen: () => (gone() ? "đã xoá" : "còn"), ok: gone });
      add(`Xoá phân loại «${name}» (biểu tượng xoá cạnh ô)`, gone(), { keys: [fk("remove", name)], guide: true });
    }
    for (const [i, o] of v.oldVariations.entries()) {
      if (o.price === undefined) continue;
      const row = optionRow(env.doc, o.name);
      add(`Giá cũ · ${o.name}: ${dong(o.price)}`, !!row && writeOptionRow(env, row, { name: o.name, price: o.price }, fk("old", i)), { keys: [fk("old", i, 0)] });
    }
  } else {
    for (const [i, o] of v.options.entries()) {
      const key = fk("option", i);
      const typeName = () => {
        if (optionBoxes(env.doc).some((b) => normalizeLabel(b.value) === normalizeLabel(o.name))) return true;
        const empty = optionBoxes(env.doc).filter((b) => b.value === "");
        // the group's empty "Nhập" box (the component adds a new empty one after each option)
        const box = empty[empty.length - 1];
        return !!box && writeBox(keyed(env, key), box, o.name);
      };
      const typedNow = i === 0 ? typeName() : false;
      if (!typedNow) env.log?.later({ key, write: typeName });
      add(`Phân loại mới: ${o.name}`, typedNow, { keys: [key] });
      const rowKey = fk("row", i);
      const writeRow = () => {
        const row = optionRow(env.doc, o.name);
        return !!row && (writeOptionRow(env, row, o, rowKey) || true);
      };
      if (!writeRow()) env.log?.later({ key: rowKey, write: writeRow });
      const parts = [o.price !== undefined ? `giá ${dong(o.price)}` : "", o.stock !== undefined ? `kho ${o.stock}` : "", o.sku ? `SKU ${o.sku}` : ""].filter(Boolean).join(", ");
      add(`${o.name}: ${parts}`, false, { keys: [`${rowKey}_0`] });
    }
  }
  return {
    steps,
    todo: [GUIDED_TODO, "Kiểm tra bảng phân loại, rồi bấm Cập nhật của Shopee. Rời trang bằng nút Hủy của Shopee."],
    notes: [NEVER_CLICKS],
  };
}

// -- the end of a programme row (undo) -------------------------------------------------------

const END_TEXTS = new Set(["kết thúc", "xóa", "xoá"]);
const MORE_TEXTS = new Set(["thêm"]);
export const PROGRAMME_END_TODO = "Bấm «Thêm» ở dòng được tô rồi «Kết thúc» (hoặc Kết thúc / Xóa nếu có sẵn), rồi xác nhận trong hộp thoại của Shopee";

/** A Flash Sale Của Shop row shows its slot as "HH:mm dd/mm/yyyy" (assumed from the form: E-case). */
export function slotRowText(slot: { day: string; label: string }): string {
  return `${slot.label.slice(0, 5)} ${dayText(slot.day)}`;
}

export function programmeRow(doc: Document, end: EndTarget, rows: HTMLElement[], byName: (r: HTMLElement) => boolean): HTMLElement | null {
  const tries: ((r: HTMLElement) => boolean)[] = [];
  if (end.id) tries.push((r) => new RegExp(`(\\D|^)${end.id}(\\D|$)`).test(Array.from(r.querySelectorAll("a[href]")).map((a) => a.getAttribute("href")).join(" ")));
  if (end.name) tries.push(byName);
  if (end.slot) {
    const want = slotRowText(end.slot);
    tries.push((r) => normalizeLabel(r.textContent ?? "").includes(normalizeLabel(want)));
  }
  for (const t of tries) {
    const hits = rows.filter(t);
    if (hits.length === 1) return hits[0]!;
  }
  return null;
}

/** Highlights the row's Kết thúc / Xóa, else its "Thêm" menu and, once the person opens it, "Kết thúc". Presses nothing. */
export function markProgrammeEnd(env: Env, row: HTMLElement): string | null {
  const direct = controlWithText(row, END_TEXTS);
  if (direct) {
    highlight(direct);
    return (direct.textContent ?? "").trim();
  }
  const more = controlWithText(row, MORE_TEXTS);
  if (!more) return null;
  highlight(more);
  env.log?.later({
    key: "end_menu",
    write: () => {
      const item = Array.from(env.doc.querySelectorAll<HTMLElement>("[role='menuitem'],li,[class*='dropdown'] *,[class*='popover'] *")).find(
        (el) => el.children.length === 0 && shown(el) && normalizeLabel(el.textContent ?? "") === "kết thúc" && !row.contains(el),
      );
      if (item) highlight(item);
      return !!item;
    },
  });
  return "Thêm";
}

