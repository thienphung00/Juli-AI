// Connector 0.3.27: the undo of an executed card (F3.1, contract B), the read-back of a saved
// object (F3.2, contract C), the product page's current values (contract D), and what the person's
// save looks like on each page (E10, E44, F2.3).
//
// The undo of a voucher / combo never presses anything: it finds the object's row on Shopee's list
// and HIGHLIGHTS its Kết thúc / Xóa control; the person presses it and answers Shopee's dialog.
// The read-back only reads.

import { FILL_LABELS, FILL_JOB_PAGES, FILL_POLL_MS, FILL_WAIT_MS } from "../config";
import type { CurrentRow, Env, FillOutcome } from "../../../core/fill/form";
import { findControl, normalizeLabel } from "../../../core/fill/locate";
import { readValue } from "../../../core/fill/write";
import { controlWithText, holdsId, usable } from "./controls";
import { markProgrammeEnd, PROGRAMME_END_TODO, programmeRow, slotRowText } from "./promos";
import type { EndTarget, FillJob } from "./job-types";

export const END_TODO = "Bấm Kết thúc (hoặc Xóa) để hoàn tác";
export const END_NOTE = "Juli không bấm Kết thúc / Xóa thay bạn.";
export const END_NO_ROW = "Không thấy dòng này trong danh sách của Shopee";
export const END_NO_CONTROL = "Dòng này không có nút Kết thúc / Xóa (có thể đã kết thúc)";
const END_TEXTS = new Set(["kết thúc", "xóa", "xoá", "end", "delete"]);
const ENDED = /(đã kết thúc|đã hết hạn|đã xóa|ended|expired|deleted)/i;
export const END_MARK = "data-juli-revert";

/** The list's rows (table rows, else Shopee's row blocks), outside dialogs and the Juli panel. */
function listRows(doc: Document): HTMLElement[] {
  const rows = Array.from(doc.querySelectorAll<HTMLElement>("tbody tr,[class*='table-row'],[role='row']")).filter(
    (r) => !/measure-row/.test(r.className.toString()) && !r.closest('[role="dialog"],[class*="modal"],[hidden]'),
  );
  return rows.filter((r) => !rows.some((o) => o !== r && r.contains(o)));
}

function linkHolds(row: Element, id: string): boolean {
  return Array.from(row.querySelectorAll<HTMLAnchorElement>("a[href]")).some((a) => new RegExp(`(\\D|^)${id}(\\D|$)`).test(a.getAttribute("href") ?? ""));
}

const leafTexts = (row: Element) =>
  [row, ...Array.from(row.querySelectorAll("*"))].filter((el) => el.children.length === 0).map((el) => normalizeLabel(el.textContent ?? ""));

/** The one row of the object: by id (link or shown id), else by code, else by name. */
export function listRowOf(doc: Document, end: EndTarget): HTMLElement | null {
  const rows = listRows(doc);
  const tries: ((r: HTMLElement) => boolean)[] = [];
  if (end.id) tries.push((r) => linkHolds(r, end.id!) || holdsId(r, end.id!));
  if (end.code) tries.push((r) => leafTexts(r).some((t) => t === end.code!.toLowerCase() || t.endsWith(end.code!.toLowerCase())));
  if (end.name) tries.push((r) => leafTexts(r).includes(normalizeLabel(end.name!)));
  for (const t of tries) {
    const hits = rows.filter(t);
    if (hits.length === 1) return hits[0] as HTMLElement;
  }
  return null;
}

/** The row's Kết thúc / Xóa control (innermost), or null; it is only ever highlighted. */
export function endControl(row: Element): HTMLElement | null {
  return controlWithText(row, END_TEXTS);
}

const endTargetOf = (job: FillJob): EndTarget | null =>
  job.payload.kind === "voucher_end" || job.payload.kind === "combo_end" || job.payload.kind === "discount_end" || job.payload.kind === "flash_sale_end" || job.payload.kind === "deal_end"
    ? job.payload.end
    : null;

const PROGRAMME_WHAT: Record<string, string> = { discount_end: "Chương Trình Của Shop", flash_sale_end: "Flash Sale Của Shop", deal_end: "Deal Sốc" };

/** The list row of a programme: by id, by its name (a leaf), or a Flash Sale slot's day and time. */
function programmeRowOf(doc: Document, end: EndTarget): HTMLElement | null {
  return programmeRow(doc, end, listRows(doc), (r) => leafTexts(r).includes(normalizeLabel(end.name ?? "")));
}

/**
 * batch-1123-a F: the undo of a Chương Trình Của Shop / Flash Sale / Deal Sốc. The row's Kết thúc /
 * Xóa is highlighted, else its "Thêm" menu and then the menu's "Kết thúc". Presses nothing.
 */
export async function fillProgrammeEnd(env: Env, job: FillJob): Promise<FillOutcome> {
  const end = endTargetOf(job);
  const what = PROGRAMME_WHAT[job.kind] ?? "chương trình";
  const label = `Dòng của ${what} ${end?.name ?? (end?.slot ? slotRowText(end.slot) : end?.id ?? "")}`.trim();
  const row = end ? await waitFor(env, () => programmeRowOf(env.doc, end), FILL_WAIT_MS) : null;
  if (!row) return { steps: [{ label, ok: false, note: END_NO_ROW }], todo: [], notes: [END_NOTE] };
  row.scrollIntoView?.({ block: "center" });
  const marked = markProgrammeEnd(env, row);
  if (!marked) return { steps: [{ label, ok: ENDED.test(row.textContent ?? ""), note: END_NO_CONTROL }], todo: [], notes: [END_NOTE] };
  row.setAttribute(END_MARK, "1");
  return { steps: [{ label: `${label}: nút «${marked}» đã được tô hồng`, ok: true }], todo: [PROGRAMME_END_TODO], notes: [END_NOTE] };
}

async function waitFor<T>(env: Env, find: () => T | null, ms: number): Promise<T | null> {
  const until = env.now() + ms;
  for (;;) {
    const found = find();
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(FILL_POLL_MS);
  }
}

/** F3.1: find the row, highlight its Kết thúc / Xóa control and say so. Presses nothing. */
export async function fillEnd(env: Env, job: FillJob): Promise<FillOutcome> {
  const end = endTargetOf(job);
  const what = job.kind === "voucher_end" ? "voucher" : "combo";
  const label = `Dòng của ${what} ${end?.code ?? end?.name ?? end?.id ?? ""}`.trim();
  const row = end ? await waitFor(env, () => listRowOf(env.doc, end), FILL_WAIT_MS) : null;
  if (!row) return { steps: [{ label, ok: false, note: END_NO_ROW }], todo: [], notes: [END_NOTE] };
  const control = endControl(row);
  if (!control) return { steps: [{ label, ok: ENDED.test(row.textContent ?? ""), note: END_NO_CONTROL }], todo: [], notes: [END_NOTE] };
  control.style.outline = "3px solid #db2777";
  control.style.outlineOffset = "2px";
  control.setAttribute(END_MARK, "1");
  row.scrollIntoView?.({ block: "center" });
  return {
    steps: [{ label: `${label}: nút «${(control.textContent ?? "").trim()}» đã được tô hồng`, ok: true }],
    todo: [END_TODO, "Rồi xác nhận trong hộp thoại của Shopee."],
    notes: [END_NOTE],
  };
}

/** Shopee's success toast after the person ended / deleted it ("Xóa thành công", "Đã kết thúc chương trình"). */
const ENDED_TOAST = /((xóa|xoá|kết thúc)[^.]{0,30}thành công|đã kết thúc chương trình|(deleted|ended) successfully)/i;

/**
 * The object is ended: its row shows an ended / deleted state (and no Kết thúc / Xóa any more), or
 * Shopee's own success toast says so. A row that only VANISHED (another tab, a filter, another
 * page of the list) is not ended: the job stays `filled`.
 */
export function endedNow(doc: Document, job: FillJob): boolean {
  const end = endTargetOf(job);
  if (!end) return false;
  const toast = Array.from(doc.querySelectorAll<HTMLElement>('[class*="toast"],[class*="message"],[class*="notification"],[role="alert"],[role="status"]')).some(
    (el) => !el.closest("[hidden]") && ENDED_TOAST.test(el.textContent ?? ""),
  );
  if (toast) return true;
  const programme = job.kind === "discount_end" || job.kind === "flash_sale_end" || job.kind === "deal_end";
  const row = programme ? programmeRowOf(doc, end) : listRowOf(doc, end);
  if (row && ENDED.test(row.textContent ?? "") && !endControl(row)) return true;
  return confirmedAndGone(doc, job, row);
}

/** a2 C-E120: per job, the highlighted row (or its marked control) that was on the page when Shopee's confirm showed. */
const confirmSeen = new Map<string, Element>();
/** Shopee's confirm of a delete / end ("Xác nhận xóa", "Bạn có chắc …", "Kết thúc chương trình?"). Assumed shape: capture 4 pending. */
const CONFIRM_TEXT = /(xóa|xoá|kết thúc|bạn có chắc|xác nhận|delete|end)/i;

function confirmDialogShown(doc: Document): boolean {
  return Array.from(doc.querySelectorAll<HTMLElement>('[role="dialog"],[role="alertdialog"],[class*="modal"],[class*="popconfirm"],[class*="confirm"]')).some(
    (el) => usable(el) && CONFIRM_TEXT.test(el.textContent ?? ""),
  );
}

/**
 * a2 C-E120 (live 23/11: combo_end stayed `filled` after Xóa + confirm, the combo gone from the
 * list): the person's confirm dialog was seen while the row Juli highlighted was on the page, the
 * dialog has closed, and that row is gone (and no row matches the job any more). A row that only
 * vanishes WITHOUT a confirm (another tab, a filter, another page) is still not ended.
 */
function confirmedAndGone(doc: Document, job: FillJob, row: HTMLElement | null): boolean {
  const marked = doc.querySelector(`[${END_MARK}]`);
  const here = marked ?? row;
  const seen = confirmSeen.get(job.id);
  // a page drawn again with the row (Shopee's list reloaded, the job reopened): start over
  if (seen && here && here !== seen) confirmSeen.delete(job.id);
  if (confirmDialogShown(doc)) {
    if (here) confirmSeen.set(job.id, here);
    return false;
  }
  const gone = !!confirmSeen.get(job.id) && !confirmSeen.get(job.id)!.isConnected && !marked && !row;
  if (gone) confirmSeen.delete(job.id);
  return gone;
}

// -- product page: current values (contract D) and read-back (contract C) -------------------

/** The first line of a description as the control shows it. */
export function firstLine(text: string): string {
  return (text.split("\n").find((l) => l.trim() !== "") ?? "").trim().slice(0, 300);
}

/** What a product's edit page shows for the item now (read only). `before` = values kept before Juli typed. */
export function productCurrent(doc: Document, itemId: string, before: Record<string, string> = {}): CurrentRow | null {
  const title = findControl(doc, FILL_LABELS.title);
  const description = findControl(doc, FILL_LABELS.description_first_line);
  const row: CurrentRow = { item_id: itemId };
  const name = before.title ?? (title ? readValue(title) : "");
  if (name.trim()) row.item_name = name.trim().slice(0, 500);
  const line = before.first_line !== undefined ? firstLine(before.first_line) : description ? firstLine(readValue(description)) : "";
  if (line) row.description_first_line = line;
  return row.item_name || row.description_first_line ? row : null;
}

/** F3.2 on a product's edit page: read the saved title and first line, report captured. */
export async function readProduct(env: Env, job: FillJob): Promise<FillOutcome> {
  const itemId = job.payload.kind === "readback" ? job.payload.readback.target.itemId : undefined;
  const read = itemId ? await waitFor(env, () => (findControl(env.doc, FILL_LABELS.title) ? productCurrent(env.doc, itemId) : null), FILL_WAIT_MS) : null;
  if (!read) return { steps: [{ label: "Đọc lại sản phẩm", ok: false, note: "Trang sản phẩm chưa hiện tên sản phẩm" }], todo: [], notes: [] };
  return { steps: [{ label: "Đọc lại sản phẩm", ok: true }], todo: [], notes: ["Juli chỉ đọc trang này."], current: [read], report: "captured" };
}

// -- the person's save --------------------------------------------------------------------

/** Shopee's success toast ("Đăng tải thành công", "Cập nhật thành công", …). */
const SAVED_TOAST = /(đăng tải|cập nhật|lưu|tạo|chỉnh sửa)[^.]{0,30}thành công|(updated|saved|created) successfully/i;

function toastShown(doc: Document): boolean {
  return Array.from(doc.querySelectorAll<HTMLElement>('[class*="toast"],[class*="message"],[class*="notification"],[role="alert"],[role="status"]')).some(
    (el) => !el.closest("[hidden]") && SAVED_TOAST.test(el.textContent ?? ""),
  );
}

/** The list row the save landed on: a voucher by its code (ending with the job's suffix) or name, a combo / programme by its name. */
function savedRowOf(doc: Document, job: FillJob): HTMLElement | null {
  const p = job.payload;
  if (p.kind === "voucher") return listRowOf(doc, { code: p.voucher.codeSuffix, name: p.voucher.name });
  if (p.kind === "combo") return listRowOf(doc, { name: p.combo.name });
  if (p.kind === "product_discount") return listRowOf(doc, { name: p.discount.name });
  if (p.kind === "add_on" || p.kind === "gift") return listRowOf(doc, { name: p.deal.name });
  return null;
}

/** a2 K2: the kinds whose save creates an object Juli reads back and undoes by its id. */
const CAPTURED_KINDS = new Set(["voucher", "combo", "product_discount", "add_on", "gift"]);
export const capturesId = (job: FillJob): boolean => job.mode === "forward" && CAPTURED_KINDS.has(job.kind);

/** An object id in a list link: `?edit=` / `id=` / `*_id=`, or a path segment after the tool's name. */
const LINK_ID = [
  /[?&](?:edit|id|voucher_id|bundle_id|bundle_deal_id|discount_id|promotion_id|add_on_deal_id)=(\d{6,20})/,
  /\/(?:vouchers|bundle|discount|add-on-deal|shop-flash-sale)\/(?:edit\/|detail\/)?(\d{6,20})(?:[/?#]|$)/,
];
/** a2 K2 (assumed, capture 3 pending): a cell that shows the id itself ("ID: 528…", or the bare number). Product ids ("Mã: …") are never taken. */
const TEXT_ID = /^(?:id\s*[:#]?\s*)?(\d{12,20})$/i;

/** F2.3 (E44, a2 K2): the new object's id from its list row: its links first, else a cell showing the id. */
export function capturedId(doc: Document, job: FillJob): string | null {
  const row = savedRowOf(doc, job);
  if (!row) return null;
  const hrefs = Array.from(row.querySelectorAll<HTMLAnchorElement>("a[href]")).map((a) => a.getAttribute("href") ?? "");
  for (const href of hrefs) {
    for (const re of LINK_ID) {
      const m = re.exec(href);
      if (m) return m[1] as string;
    }
  }
  for (const leaf of leafTexts(row)) {
    const m = TEXT_ID.exec(leaf);
    if (m) return m[1] as string;
  }
  return null;
}

/** The save of each kind's page, as the follow loop sees it. */
export function savedOn(doc: Document, loc: { pathname: string }, job: FillJob): boolean {
  // live 23/11 (E118): the combo save lands on /portal/marketing/list/discount/ (a trailing slash)
  const path = loc.pathname.length > 1 ? loc.pathname.replace(/\/+$/, "") : loc.pathname;
  switch (job.kind) {
    case "voucher":
      return FILL_JOB_PAGES.voucher_list.test(path);
    case "combo":
      // E118: Khuyến Mãi của Shop's list (discountType=all…), or the combo list
      return FILL_JOB_PAGES.bundle_list.test(path) || FILL_JOB_PAGES.discount_list.test(path);
    case "voucher_end":
    case "combo_end":
    case "discount_end":
    case "flash_sale_end":
    case "deal_end":
      return endedNow(doc, job);
    // batch-1123-a F: the person's Xác nhận lands on the programme's list (assumed, E-case for the
    // first E2E run); a Deal Sốc's step-1 Lưu does not count, only the list after Xác nhận
    case "product_discount":
    case "add_on":
    case "gift":
      return FILL_JOB_PAGES.discount_list.test(path) || /^\/portal\/marketing\/add-on-deal\/list/.test(path);
    case "flash_sale":
      return FILL_JOB_PAGES.flash_sale_list.test(path);
    case "readback":
      return false;
    default:
      return toastShown(doc) || (job.kind !== "affiliate_commission" && /^\/portal\/product\/list/.test(path));
  }
}

export function captureOn(doc: Document, job: FillJob): string | null {
  return capturesId(job) ? capturedId(doc, job) : null;
}
