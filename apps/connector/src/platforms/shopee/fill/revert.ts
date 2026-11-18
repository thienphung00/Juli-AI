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
import { controlWithText, holdsId } from "./controls";
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

const endTargetOf = (job: FillJob): EndTarget | null => (job.payload.kind === "voucher_end" || job.payload.kind === "combo_end" ? job.payload.end : null);

/** Jobs whose row this page showed (so a row that is gone afterwards means it was deleted). */
const seenRows = new Set<string>();

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
  seenRows.add(job.id);
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

/** The object is ended or gone: its row says so, or the row this page showed is no longer listed. */
export function endedNow(doc: Document, job: FillJob): boolean {
  const end = endTargetOf(job);
  if (!end) return false;
  const row = listRowOf(doc, end);
  if (row) return ENDED.test(row.textContent ?? "") && !endControl(row);
  return seenRows.has(job.id) && listRows(doc).length > 0;
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

/** The voucher's code as Shopee lists it ends with the job's suffix. */
function voucherRowOf(doc: Document, job: FillJob): HTMLElement | null {
  if (job.payload.kind === "voucher") return listRowOf(doc, { code: job.payload.voucher.codeSuffix, name: job.payload.voucher.name });
  if (job.payload.kind === "combo") return listRowOf(doc, { name: job.payload.combo.name });
  return null;
}

/** F2.3 (E44): the new object's id from its row's edit link (`edit=<id>`, `/<id>`), digits only. */
export function capturedId(doc: Document, job: FillJob): string | null {
  const row = voucherRowOf(doc, job);
  if (!row) return null;
  const hrefs = Array.from(row.querySelectorAll<HTMLAnchorElement>("a[href]")).map((a) => a.getAttribute("href") ?? "");
  for (const href of hrefs) {
    const m = /[?&](?:edit|id|voucher_id|bundle_id)=(\d{6,20})/.exec(href) ?? /\/(?:vouchers|bundle)\/(?:edit\/|detail\/)?(\d{6,20})(?:[/?#]|$)/.exec(href);
    if (m) return m[1] as string;
  }
  return null;
}

/** The save of each kind's page, as the follow loop sees it. */
export function savedOn(doc: Document, loc: { pathname: string }, job: FillJob): boolean {
  switch (job.kind) {
    case "voucher":
      return FILL_JOB_PAGES.voucher_list.test(loc.pathname);
    case "combo":
      return FILL_JOB_PAGES.bundle_list.test(loc.pathname);
    case "voucher_end":
    case "combo_end":
      return endedNow(doc, job);
    case "readback":
      return false;
    default:
      return toastShown(doc) || (job.kind !== "affiliate_commission" && /^\/portal\/product\/list/.test(loc.pathname));
  }
}

export function captureOn(doc: Document, job: FillJob): string | null {
  return job.kind === "voucher" || job.kind === "combo" ? capturedId(doc, job) : null;
}
