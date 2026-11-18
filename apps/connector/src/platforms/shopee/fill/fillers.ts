// The page fillers of a fill job: voucher form, ads edit popups, affiliate bulk commission edit.
// Each types / chooses / ticks what the approved card holds, one labelled field at a time, and
// returns a checklist. None presses Shopee's Lưu / Lưu lại / Xác nhận / Gửi / Cập nhật: the person
// does (controls.press refuses those texts). Labels are the visible Vietnamese ones recorded on
// ORY's Seller Centre (fasttrack/contracts/p97-recon-2026-11-09.md).

import {
  chooseRadio,
  type PickResult,
  writeBox,
  chooseSelect,
  ensureCount,
  type Env,
  findDialog,
  findEditPencil,
  findPressable,
  findRow,
  holdsId,
  pickProducts,
  press,
  setDate,
  setRowText,
  setSwitch,
  textBoxesIn,
} from "./controls";
import type { AdsPayload, AffiliatePayload, ComboPayload, FillJob, VoucherPayload } from "./job-types";
import { normalizeLabel } from "../../../core/fill/locate";
import { keyed } from "../../../core/fill/log";
import { writeValue } from "../../../core/fill/write";

export type { FillOutcome, Step } from "../../../core/fill/form";
import type { CurrentRow, FillOutcome, Step } from "../../../core/fill/form";

const dong = (n: number) => `${n.toLocaleString("vi-VN")} ₫`;

export const VOUCHER_LABELS = {
  name: "Tên chương trình giảm giá",
  code: "Mã voucher",
  period: "Thời gian sử dụng mã",
  type: "Loại Voucher",
  /** Not on the live page any more (2026-11-17): set off only when Shopee still draws it. */
  smart: "Mã giảm giá thông minh",
  discount: "Loại giảm giá | Mức giảm",
  max: "Mức giảm tối đa",
  minSpend: "Giá trị đơn hàng tối thiểu",
  usageTotal: "Tổng lượt sử dụng tối đa",
  perBuyer: "Lượt sử dụng tối đa/Người mua",
  display: "Thiết lập hiển thị",
  products: "Sản phẩm được áp dụng",
} as const;

const DISPLAY_OPTION = { multi: "Hiển thị nhiều nơi", code: "Chia sẻ thông qua mã Voucher", private: "Không công khai" } as const;
/** Every spelling of a display option seen on Seller Centre (and on Juli's card: "Chia sẻ qua mã voucher"). */
const DISPLAY_ALIASES = {
  multi: ["Hiển thị nhiều nơi"],
  code: ["Chia sẻ thông qua mã Voucher", "Chia sẻ qua mã voucher"],
  private: ["Không công khai"],
} as const;
export const SMART_MISSING = "Trang không có ô «Mã giảm giá thông minh»; bật tay nếu cần";

/** The field keys of a fill (the job report's `before_values` and `fields` use them). */
export const PERIOD_KEYS = ["starts_at", "ends_at"];
export const PERIOD_NOTE = "Chọn tay thời gian theo thẻ — Shopee đang để mặc định là bây giờ.";

type Add = (label: string, ok: boolean, opts?: { note?: string; keys?: string[] }) => void;

function stepper(steps: Step[]): Add {
  return (label, ok, opts = {}) =>
    steps.push({ label, ok, ...(opts.note && !ok ? { note: opts.note } : {}), ...(opts.keys ? { keys: opts.keys } : {}) });
}

async function period(env: Env, add: Add, label: string, startsAt: string, endsAt: string): Promise<void> {
  // the end first would be refused while the start is still "now" + 1 h: start, then end
  const start = await setDate(keyed(env, "starts_at"), label, startsAt, 0);
  const end = await setDate(keyed(env, "ends_at"), label, endsAt, 1);
  add(`Thời gian: ${startsAt} → ${endsAt}`, start && end, { note: PERIOD_NOTE, keys: PERIOD_KEYS });
}

function picked(add: Add, p: PickResult, total: number): void {
  // a picker whose own Xác nhận could not be pressed is not done (0.3.27)
  add(`Sản phẩm: ${p.ticked.length}/${total} ${p.confirmed ? "đã chọn" : "đã tick"}`, p.missing.length === 0 && p.confirmed !== false, {
    keys: ["product_ids"],
    ...(p.reason ? { note: p.reason } : {}),
  });
}

export async function fillVoucher(env: Env, v: VoucherPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  const L = VOUCHER_LABELS;
  const k = (key: string) => keyed(env, key);
  add(`Tên chương trình: ${v.name}`, setRowText(k("name"), L.name, v.name), { keys: ["name"] });
  add(`Mã voucher: …${v.codeSuffix}`, setRowText(k("code_suffix"), L.code, v.codeSuffix), { keys: ["code_suffix"] });
  await period(env, add, L.period, v.startsAt, v.endsAt);
  add("Loại voucher: Khuyến Mãi", await chooseRadio(k("voucher_type"), L.type, "Khuyến Mãi"), { keys: ["voucher_type"] });
  // 0.3.27: set to the card's value when Shopee draws it; a card that wants it on and a page without it is ✗
  if (findRow(env.doc, L.smart)) add(`Mã giảm giá thông minh: ${v.smart ? "bật" : "tắt"}`, await setSwitch(k("smart"), L.smart, v.smart), { keys: ["smart"] });
  else if (v.smart) add("Mã giảm giá thông minh: bật", false, { note: SMART_MISSING });
  if (v.discount.type === "amount") {
    const kind = await chooseSelect(k("discount_type"), L.discount, "Theo số tiền");
    add(`Giảm ${dong(v.discount.value)}`, kind && setRowText(k("discount"), L.discount, String(v.discount.value)), {
      keys: ["discount_type", "discount"],
    });
  } else {
    const kind = await chooseSelect(k("discount_type"), L.discount, "Theo phần trăm");
    add(`Giảm ${v.discount.value}%`, kind && setRowText(k("discount"), L.discount, String(v.discount.value)), {
      keys: ["discount_type", "discount"],
    });
    if (v.discount.max.mode === "limited") {
      const radio = await chooseRadio(k("max_mode"), L.max, "Giới hạn");
      add(`Giảm tối đa ${dong(v.discount.max.value)}`, radio && setRowText(k("max_value"), L.max, String(v.discount.max.value)), {
        keys: ["max_mode", "max_value"],
      });
    } else {
      add("Giảm tối đa: không giới hạn", await chooseRadio(k("max_mode"), L.max, "Không giới hạn"), { keys: ["max_mode"] });
    }
  }
  add(`Đơn tối thiểu ${dong(v.minSpend)}`, setRowText(k("min_spend"), L.minSpend, String(v.minSpend)), { keys: ["min_spend"] });
  add(`Tổng lượt dùng ${v.usageTotal}`, setRowText(k("usage_total"), L.usageTotal, String(v.usageTotal)), { keys: ["usage_total"] });
  add(`Mỗi người mua ${v.perBuyer} lượt`, setRowText(k("per_buyer"), L.perBuyer, String(v.perBuyer)), { keys: ["per_buyer"] });
  add(`Hiển thị: ${DISPLAY_OPTION[v.display]}`, await chooseRadio(k("display"), L.display, DISPLAY_ALIASES[v.display]), { keys: ["display"] });
  const todo: string[] = [];
  if (v.productIds.length > 0) {
    const p = await pickProducts(k("product_ids"), "Thêm sản phẩm", v.productIds, { confirm: true });
    picked(add, p, v.productIds.length);
    if (!p.confirmed) todo.push("Bấm Xác nhận trong hộp chọn sản phẩm.");
  }
  todo.push("Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo voucher.");
  return { steps, todo, notes: ["Juli không bấm Xác nhận thay bạn."], periodKeys: PERIOD_KEYS };
}

// -- combo khuyến mãi (bundle deal) ----------------------------------------------------------

export const COMBO_LABELS = {
  name: "Tên Combo Khuyến Mãi",
  period: "Thời gian chạy Combo",
  type: "Loại Combo",
  tiers: "Mức ưu đãi",
  addTier: "Thêm mức ưu đãi",
  limit: "Giới hạn đặt hàng",
  products: "Thêm sản phẩm",
} as const;

const COMBO_TYPE_OPTION = { pct: "Giảm giá theo %", amount: "Giảm giá theo số tiền", special_price: "Giảm giá đặc biệt" } as const;
const COMBO_TIER_TEXT = {
  pct: (q: number, v: number) => `Mua ${q} giảm ${v}%`,
  amount: (q: number, v: number) => `Mua ${q} giảm ${dong(v)}`,
  special_price: (q: number, v: number) => `Mua ${q} chỉ với giá ${dong(v)}`,
} as const;

/**
 * The tier rows, in order, each holding its two boxes ("Mua [N] sản phẩm để được giảm [X]"):
 * under the "Mức ưu đãi" row when Shopee labels it, else every innermost element whose text reads
 * "Mua … sản phẩm …" and holds exactly two boxes (the live page, 2026-11-17).
 */
export function tierRows(doc: Document): HTMLInputElement[][] {
  // live 2026-11-18: one table row per tier, the text split around the boxes; the boxes carry the
  // CSS-module names minAmount (N) and discountValue / discountInput (X)
  const live = Array.from(doc.querySelectorAll<HTMLElement>("tr,[class*='table-row']"))
    .map((r) => [r.querySelector<HTMLInputElement>('[class*="minAmount"] input'), r.querySelector<HTMLInputElement>('[class*="discountValue"] input,[class*="discountInput"] input')] as const)
    .filter((pair): pair is readonly [HTMLInputElement, HTMLInputElement] => !!pair[0] && !!pair[1] && textBoxesIn(pair[0].parentElement!).length > 0 && textBoxesIn(pair[1].parentElement!).length > 0);
  const uniq = live.filter((pair, i) => live.findIndex((o) => o[0] === pair[0]) === i);
  if (uniq.length > 0) return uniq.map((pair) => [pair[0], pair[1]]);
  const labelled = findRow(doc, COMBO_LABELS.tiers);
  const scope: ParentNode = labelled ?? doc.body;
  const rows = Array.from(scope.querySelectorAll<HTMLElement>("div,li,tr")).filter(
    (el) => /^mua.*sản phẩm/.test(normalizeLabel((el.textContent ?? "").slice(0, 200))) && textBoxesIn(el).length === 2,
  );
  const inner = rows.filter((r) => !rows.some((o) => o !== r && r.contains(o)));
  if (inner.length > 0) return inner.map((r) => textBoxesIn(r));
  // one row element holding every tier's pair of boxes
  if (!labelled) return [];
  const boxes = textBoxesIn(labelled);
  const out: HTMLInputElement[][] = [];
  for (let i = 0; i + 1 < boxes.length; i += 2) out.push([boxes[i]!, boxes[i + 1]!]);
  return out;
}

export async function fillCombo(env: Env, c: ComboPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  const L = COMBO_LABELS;
  const k = (key: string) => keyed(env, key);
  // the type first: it decides what the tier rows ask for
  add(`Loại combo: ${COMBO_TYPE_OPTION[c.discountType]}`, await chooseRadio(k("discount_type"), L.type, COMBO_TYPE_OPTION[c.discountType]), {
    keys: ["discount_type"],
  });
  add(`Tên combo: ${c.name}`, setRowText(k("name"), L.name, c.name), { keys: ["name"] });
  await period(env, add, L.period, c.startsAt, c.endsAt);
  // 0.3.27 (E48): tier by tier: Shopee enables "Thêm mức ưu đãi" only once the tier above is valid
  for (const [i, t] of c.tiers.entries()) {
    const keys = [`tier${i + 1}_qty`, `tier${i + 1}_value`];
    if (tierRows(env.doc).length < i + 1) await addTier(env, i + 1);
    const row = tierRows(env.doc)[i];
    const ok = !!row && writeBox(k(keys[0]!), row[0]!, String(t.qty)) && writeBox(k(keys[1]!), row[1]!, String(t.value));
    add(COMBO_TIER_TEXT[c.discountType](t.qty, t.value), ok, { keys, note: row ? undefined : TIER_MISSING });
  }
  if (c.purchaseLimit !== undefined) {
    add(`Giới hạn đặt hàng: ${c.purchaseLimit}`, setRowText(k("purchase_limit"), L.limit, String(c.purchaseLimit)), { keys: ["purchase_limit"] });
  }
  const p = await pickProducts(k("product_ids"), L.products, c.productIds, { confirm: true });
  picked(add, p, c.productIds.length);
  return {
    steps,
    todo: [...(p.confirmed ? [] : ["Bấm Xác nhận trong hộp chọn sản phẩm."]), "Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo combo."],
    notes: ["Juli không bấm Xác nhận thay bạn."],
    periodKeys: PERIOD_KEYS,
  };
}

export const TIER_MISSING = "Không thấy dòng «Mua … sản phẩm» của mức này";

/** Presses "Thêm mức ưu đãi" once it is enabled (Shopee marks it with a `disabled` class), then waits for row `n`. */
async function addTier(env: Env, n: number): Promise<boolean> {
  const enabled = () => {
    const add = findPressable(env, COMBO_LABELS.addTier);
    const holder = add?.closest("button") ?? add;
    return add && holder && !/\bdisabled\b/.test(holder.className.toString()) && !(holder as HTMLButtonElement).disabled ? add : null;
  };
  const add = await waitFor(env, enabled, 2_000);
  if (!add || !press(add)) return false;
  return !!(await waitFor(env, () => (tierRows(env.doc).length >= n ? true : null), 1_500));
}

// -- ads edit ------------------------------------------------------------------------------

export const ADS_LABELS = {
  budgetCard: "Ngân sách",
  budgetDialog: "Chỉnh sửa ngân sách",
  roasCard: "Mục tiêu ROAS",
  roasDialog: "Mục tiêu ROAS",
  daily: "Ngân sách hàng ngày",
  unlimited: "Không giới hạn",
  custom: "Tùy chỉnh",
} as const;
export const ROAS_HINT_MAX = 3.5;

async function openDialog(env: Env, card: string, heading: string): Promise<HTMLElement | null> {
  const existing = findDialog(env, heading);
  if (existing) return existing;
  const pencil = findEditPencil(env, card);
  if (!pencil || !press(pencil)) return null;
  const until = env.now() + 4_000;
  for (;;) {
    const d = findDialog(env, heading);
    if (d) return d;
    if (env.now() >= until) return null;
    await env.sleep(150);
  }
}

export async function fillAds(env: Env, a: AdsPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const notes: string[] = [];
  const todo: string[] = [];
  if (a.budget) {
    const dialog = await openDialog(env, ADS_LABELS.budgetCard, ADS_LABELS.budgetDialog);
    if (!dialog) {
      steps.push({ label: "Mở cửa sổ Chỉnh sửa ngân sách", ok: false, note: "Không thấy nút bút chì của ngân sách." });
    } else if (a.budget.mode === "unlimited") {
      steps.push({
        label: "Ngân sách: Không giới hạn",
        ok: await chooseRadio(keyed(env, "budget_mode"), ADS_LABELS.unlimited, ADS_LABELS.unlimited, dialog),
        keys: ["budget_mode"],
      });
    } else {
      const radio = await chooseRadio(keyed(env, "budget_mode"), ADS_LABELS.daily, ADS_LABELS.daily, dialog);
      const typed = textBoxesIn(dialog)[0];
      const ok = radio && !!typed && writeBox(keyed(env, "daily_budget"), typed, String(a.budget.value));
      steps.push({ label: `Ngân sách hàng ngày: ${dong(a.budget.value)}`, ok, keys: ["budget_mode", "daily_budget"] });
    }
    todo.push("Bấm Xác nhận trong cửa sổ ngân sách của Shopee.");
    if (a.roas) notes.push("Mục tiêu ROAS: làm ở lần mở trang kế tiếp (mỗi lần chỉ một cửa sổ).");
  } else if (a.roas) {
    const dialog = await openDialog(env, ADS_LABELS.roasCard, ADS_LABELS.roasDialog);
    if (!dialog) {
      steps.push({ label: "Mở cửa sổ Mục tiêu ROAS", ok: false, note: "Không thấy nút bút chì của ROAS." });
    } else {
      const radio = await chooseRadio(keyed(env, "roas_mode"), ADS_LABELS.custom, ADS_LABELS.custom, dialog);
      const typed = textBoxesIn(dialog)[0];
      const ok = radio && !!typed && writeBox(keyed(env, "roas_target"), typed, String(a.roas.value));
      steps.push({ label: `Mục tiêu ROAS: ${a.roas.value}`, ok, keys: ["roas_mode", "roas_target"] });
    }
    if (a.roas.value > ROAS_HINT_MAX) notes.push(`Shopee gợi ý ROAS ≤ ${ROAS_HINT_MAX}; giá trị này cao hơn.`);
    notes.push("Đổi ROAS từ 2 lần trong một tuần sẽ mất hỗ trợ hiệu quả của tuần đó.");
    todo.push("Bấm Xác nhận trong cửa sổ ROAS của Shopee.");
  }
  return { steps, todo, notes };
}

// -- affiliate: open campaign (Chiến dịch mở rộng) commission ----------------------------------
//
// 0.3.27 (E51): the page opens under Shopee's "new version" notice (closed by the runner, never via
// "Khám phá Ngay"), lists 100+ products over several pages, and rendered in Vietnamese or English
// (2026-11-18). The product's row is found by its id (the page's search, else page by page); its
// own rate control is opened and the rate typed; Shopee's Lưu / Lưu lại stays with the person.
// The rate it showed is kept as the before value (the revert puts it back).

export const AFFILIATE_LABELS = {
  bulk: ["Chỉnh sửa hàng loạt", "Batch Edit"],
  commission: ["Chỉnh sửa tỉ lệ hoa hồng", "Edit Commission Rate", "Edit Commission"],
  search: ["Tìm kiếm", "Tìm", "Search"],
} as const;
export const AFFILIATE_NO_FILTER = "Không thấy ô tìm sản phẩm theo tên / ID trên trang Chiến dịch mở rộng";
export const AFFILIATE_NO_ROW = (ids: readonly string[]) => `Không thấy dòng của ID ${ids.join(", ")} (đã tìm và xem các trang)`;
export const AFFILIATE_NO_EDITOR = "Không mở được ô sửa tỉ lệ của dòng này";
const MAX_PAGES = 15;

function pressableOf(env: Env, texts: readonly string[], within?: Element): HTMLElement | null {
  for (const t of texts) {
    const hit = findPressable(env, t, within);
    if (hit) return hit;
  }
  return null;
}

/** The list's product rows (not the table's measure row). */
function campaignRows(doc: Document): HTMLElement[] {
  return Array.from(doc.querySelectorAll<HTMLElement>("tbody tr,[role='row']")).filter(
    (r) => !/measure-row/.test(r.className.toString()) && !r.closest('[role="dialog"],[class*="modal"]') && !r.closest("[hidden]"),
  );
}

/** The row showing this product id, or null (none, or more than one). */
export function affiliateRowOf(doc: Document, id: string): HTMLElement | null {
  const rows = campaignRows(doc).filter((r) => holdsId(r, id));
  const inner = rows.filter((h) => !rows.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (inner[0] as HTMLElement) : null;
}

const RATE = /^(\d{1,2}(?:[.,]\d{1,2})?)\s*%$/;

/** The rate cell of a row ("13%") and its value, or null. */
export function rateOf(row: Element): { cell: HTMLElement; pct: number } | null {
  for (const el of Array.from(row.querySelectorAll<HTMLElement>("*"))) {
    const m = el.children.length === 0 ? RATE.exec((el.textContent ?? "").trim()) : null;
    if (m) return { cell: (el.closest("td") ?? el.parentElement ?? el) as HTMLElement, pct: Number(m[1]!.replace(",", ".")) };
  }
  return null;
}

const ROW_ID = /(?:product id|id sản phẩm|mã sản phẩm|\bid)\s*:?\s*(\d{3,20})/i;

/** Contract D (E50): the products the page shows with their commission (read only). */
export function affiliateRates(doc: Document): CurrentRow[] {
  const out: CurrentRow[] = [];
  for (const row of campaignRows(doc)) {
    const id = ROW_ID.exec((row.textContent ?? "").replace(/\s+/g, " "))?.[1];
    const rate = rateOf(row);
    if (id && rate && rate.pct >= 0 && rate.pct <= 100 && !out.some((o) => o.item_id === id)) out.push({ item_id: id, commission_pct: rate.pct });
  }
  return out;
}

function filterBox(env: Env): HTMLInputElement | null {
  const boxes = Array.from(env.doc.querySelectorAll<HTMLInputElement>('input:not([type]),input[type="text"],input[type="search"]')).filter(
    (i) => !i.closest('[role="dialog"],[class*="modal"]') && !i.readOnly && /(tìm|tên sản phẩm|id|search|product)/i.test(i.placeholder),
  );
  return boxes.length === 1 ? (boxes[0] as HTMLInputElement) : null;
}

const PAGER_NEXT = [
  '[class*="pagination"] [class*="next"]',
  '[class*="pager"] [class*="next"]',
  '[aria-label*="next" i]',
  '[aria-label*="trang sau" i]',
];

function nextPage(env: Env): HTMLElement | null {
  for (const sel of PAGER_NEXT) {
    const hit = Array.from(env.doc.querySelectorAll<HTMLElement>(sel)).find(
      (el) => !/\bdisabled\b/.test(el.className.toString()) && !(el as HTMLButtonElement).disabled && el.getAttribute("aria-disabled") !== "true" && !el.closest("[hidden]"),
    );
    if (hit) return hit;
  }
  return null;
}

/** Finds the product's row: on the page, through the page's search box, then page by page. */
async function findCampaignRow(env: Env, id: string): Promise<{ row: HTMLElement | null; searched: boolean }> {
  const here = await waitFor(env, () => affiliateRowOf(env.doc, id), 3_000);
  if (here) return { row: here, searched: false };
  const box = filterBox(env);
  if (box && writeValue(box, id)) {
    const go = pressableOf(env, AFFILIATE_LABELS.search);
    if (go) press(go);
    const found = await waitFor(env, () => affiliateRowOf(env.doc, id), 4_000);
    if (found) return { row: found, searched: true };
  }
  let paged = false;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const next = nextPage(env);
    if (!next) break;
    paged = true;
    const before = campaignRows(env.doc).map((r) => r.textContent).join("|");
    if (!press(next)) break;
    if (!(await waitFor(env, () => (campaignRows(env.doc).map((r) => r.textContent).join("|") !== before ? true : null), 4_000))) break;
    const found = affiliateRowOf(env.doc, id);
    if (found) return { row: found, searched: true };
  }
  return { row: null, searched: !!box || paged };
}

/** The row's own rate control: marked edit, else the one icon next to the rate. */
function rateEditor(cell: HTMLElement): HTMLElement | null {
  const marked = Array.from(cell.querySelectorAll<HTMLElement>('[aria-label*="edit" i],[aria-label*="chỉnh sửa" i],[title*="chỉnh sửa" i],[title*="edit" i],[class*="edit"]'));
  if (marked.length === 1) return marked[0] as HTMLElement;
  const icons = Array.from(cell.querySelectorAll("svg")).map((svg) => svg.parentElement).filter((el): el is HTMLElement => !!el && el !== cell);
  return icons.length === 1 ? (icons[0] as HTMLElement) : null;
}

/** The dialog / popover with a text box that opened for the rate. */
function rateBox(env: Env): HTMLInputElement | null {
  const holders = Array.from(env.doc.querySelectorAll<HTMLElement>('[role="dialog"],[class*="modal"],[class*="popover"],[class*="popper"]')).filter(
    (d) => !d.hidden && !d.closest("[hidden]") && textBoxesIn(d).length > 0,
  );
  const inner = holders.filter((h) => !holders.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (textBoxesIn(inner[0]!)[0] ?? null) : null;
}

export async function fillAffiliate(env: Env, a: AffiliatePayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const current = affiliateRates(env.doc);
  const rows: HTMLElement[] = [];
  const missing: string[] = [];
  let searched = false;
  for (const id of a.productIds) {
    const found = await findCampaignRow(env, id);
    searched = searched || found.searched;
    if (found.row) rows.push(found.row);
    else missing.push(id);
  }
  for (const r of affiliateRates(env.doc)) if (!current.some((c) => c.item_id === r.item_id)) current.push(r);
  steps.push({
    label: `Tìm sản phẩm: ${rows.length}/${a.productIds.length}`,
    ok: missing.length === 0,
    ...(missing.length > 0 ? { note: searched ? AFFILIATE_NO_ROW(missing) : `${AFFILIATE_NO_ROW(missing)} — ${AFFILIATE_NO_FILTER}` } : {}),
  });
  let dialogOk = false;
  let why = "Chưa tìm được sản phẩm nên Juli không mở ô sửa hoa hồng";
  const before = rows.length === 1 ? rateOf(rows[0]!) : null;
  if (before) env.log?.captureBefore("commission_pct", String(before.pct));
  if (missing.length === 0 && rows.length === 1 && before) {
    // the row's own control
    const editor = rateEditor(before.cell);
    if (editor && press(editor)) {
      const box = await waitFor(env, () => rateBox(env), 3_000);
      dialogOk = !!box && writeBox(keyed(env, "commission_pct"), box, String(a.commissionPct));
      why = box ? "Shopee chưa nhận tỉ lệ" : AFFILIATE_NO_EDITOR;
    } else why = AFFILIATE_NO_EDITOR;
  }
  if (!dialogOk && missing.length === 0 && rows.length > 0) {
    // several products, or no control of its own: tick the rows, then the bulk edit
    const ticked = rows.every((r) => {
      const check = r.querySelector<HTMLElement>('input[type="checkbox"],[role="checkbox"]');
      if (!check) return false;
      const on = () => (check.matches("input") ? (check as HTMLInputElement).checked : check.getAttribute("aria-checked") === "true");
      return on() || press(check);
    });
    const bulk = ticked ? pressableOf(env, AFFILIATE_LABELS.bulk) : null;
    if (bulk && press(bulk)) {
      const item = await waitFor(env, () => pressableOf(env, AFFILIATE_LABELS.commission), 3_000);
      if (item && press(item)) {
        const box = await waitFor(env, () => rateBox(env), 3_000);
        dialogOk = !!box && writeBox(keyed(env, "commission_pct"), box, String(a.commissionPct));
        if (!dialogOk) why = "Không thấy ô tỉ lệ trong hộp thoại";
      } else why = "Không thấy mục «Chỉnh sửa tỉ lệ hoa hồng»";
    } else if (!dialogOk && why === "Chưa tìm được sản phẩm nên Juli không mở ô sửa hoa hồng") why = "Không thấy nút «Chỉnh sửa hàng loạt»";
  }
  steps.push({ label: `Tỉ lệ hoa hồng: ${a.commissionPct}%`, ok: dialogOk, keys: ["commission_pct"], ...(dialogOk ? {} : { note: why }) });
  return {
    steps,
    todo: ["Kiểm tra tỉ lệ trong hộp thoại, rồi bấm Lưu / Lưu lại của Shopee."],
    notes: ["Juli không bấm Lưu thay bạn."],
    ...(current.length > 0 ? { current } : {}),
  };
}

/**
 * F3.2 (contract C) on the open campaign: find each product's row (search, else page by page),
 * read the rates the page shows and report captured. Nothing is opened, typed or ticked.
 */
export async function readAffiliate(env: Env, job: FillJob): Promise<FillOutcome> {
  const ids = job.payload.kind === "readback" ? (job.payload.readback.target.productIds ?? []) : [];
  const current = affiliateRates(env.doc);
  const missing: string[] = [];
  for (const id of ids) {
    const found = await findCampaignRow(env, id);
    if (!found.row) missing.push(id);
    for (const r of affiliateRates(env.doc)) if (!current.some((c) => c.item_id === r.item_id)) current.push(r);
  }
  const read = ids.length > 0 && missing.length === 0;
  return {
    steps: [{ label: `Đọc lại hoa hồng: ${ids.length - missing.length}/${ids.length}`, ok: read, ...(read ? {} : { note: AFFILIATE_NO_ROW(missing) }) }],
    todo: [],
    notes: ["Juli chỉ đọc trang này."],
    ...(current.length > 0 ? { current } : {}),
    ...(read ? { report: "captured" as const } : {}),
  };
}

async function waitFor<T>(env: Env, find: () => T | null | undefined, ms = 4_000): Promise<T | null> {
  const until = env.now() + ms;
  for (;;) {
    const found = find();
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(150);
  }
}

async function waitPressable(env: Env, text: string): Promise<HTMLElement | null> {
  const until = env.now() + 3_000;
  for (;;) {
    const found = findPressable(env, text);
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(150);
  }
}

async function waitDialog(env: Env, heading: string): Promise<HTMLElement | null> {
  const until = env.now() + 3_000;
  for (;;) {
    const found = findDialog(env, heading);
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(150);
  }
}
