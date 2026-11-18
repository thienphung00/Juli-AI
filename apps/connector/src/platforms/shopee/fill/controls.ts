// The controls a fill job needs beyond a text box (P97 D85.6): radios, selects, date pickers,
// switches, repeated rows and a product picker. Shopee's `eds-react-*` components are found by the
// VISIBLE LABEL next to them, never by class name alone. Anything unclear (no row, a label twice,
// no such option) returns false and nothing is touched.
//
// This is the ONLY fill file that may press something, and only through `press()`, which refuses a
// button that saves, sends, confirms, deletes or cancels (Lưu, Lưu lại, Xác nhận, Gửi, Cập nhật,
// Tạo, Đăng, Xóa, Loại bỏ, Hủy, Ẩn, Áp dụng) or that submits a form. Opening a drop-down, choosing
// a radio / option, switching a switch, adding a row, ticking a product and the "Chỉnh sửa hàng
// loạt" menu are presses; Shopee's own save is never one.

import { normalizeLabel, PANEL_ID } from "../../../core/fill/locate";
import { writeValue } from "../../../core/fill/write";
import { MAX_BEFORE_CHARS } from "../../../core/fill/log";

export type { Env } from "../../../core/fill/form";
import type { Env } from "../../../core/fill/form";

export const WAIT_MS = 4_000;
const POLL_MS = 150;

/** Texts that end in Shopee saving, sending, confirming, deleting or cancelling something. */
export const FORBIDDEN_PRESS =
  /^(lưu|lưu lại|lưu ở dạng nháp|xác nhận|gửi|gửi đi|cập nhật|tạo|tạo mới|đăng|xóa|xoá|kết thúc|loại bỏ|hủy|ẩn|áp dụng|hoàn tất|đồng ý|khám phá ngay|submit|save|confirm|send|delete|remove|end|explore now|ok)$/;

function visibleText(el: Element): string {
  return normalizeLabel((el.textContent ?? "").slice(0, 80));
}

function hidden(el: Element): boolean {
  if (el.closest("[hidden],[aria-hidden='true']")) return true;
  const view = el.ownerDocument.defaultView;
  for (let node: Element | null = el; node; node = node.parentElement) {
    const style = view?.getComputedStyle(node);
    if (style && (style.display === "none" || style.visibility === "hidden")) return true;
  }
  return false;
}

const inPanel = (el: Element) => !!el.closest(`#${PANEL_ID}`);
const usable = (el: Element) => !inPanel(el) && !hidden(el);

/** Why a press was refused (for tests and for the log): the text or the type that made it unsafe. */
export function unsafePress(el: Element): string | null {
  const text = visibleText(el);
  if (FORBIDDEN_PRESS.test(text)) return text;
  const submits = (b: Element) =>
    (b.tagName === "BUTTON" || b.tagName === "INPUT") &&
    ((b.getAttribute("type") ?? "").toLowerCase() === "submit" || ((b as HTMLButtonElement).type === "submit" && !!(b as HTMLButtonElement).form));
  if (submits(el)) return "type=submit";
  const button = el.closest("button");
  if (button && button !== el) {
    const inner = visibleText(button);
    if (FORBIDDEN_PRESS.test(inner)) return inner;
    if (submits(button)) return "type=submit";
  }
  return null;
}

/** The single place the fill code presses something. Returns false (and presses nothing) when unsafe.
 * 0.3.27: always the element's own native click(), never a synthesized MouseEvent (Shopee's
 * anti-bot sent a synthetic click to /verify/traffic/error, 2026-11-18). */
export function press(el: HTMLElement): boolean {
  if (unsafePress(el) !== null) return false;
  el.click();
  return true;
}

/**
 * The two confirms the Connector may press (owner, 2026-11-18): the date-time picker's own
 * "Xác nhận" (inside `.eds-react-date-picker__btn-wrap` of the picker's popover) and the product
 * picker's own "Xác nhận" (in the footer of the `.product-selector` dialog). Every other confirm,
 * the form's own Xác nhận / Lưu / Cập nhật included, is still refused.
 */
export type OwnConfirm = "date_picker" | "product_picker";
const CONFIRM_TEXT = /^(xác nhận|confirm|ok)$/;

export function ownConfirmOf(el: Element, kind: OwnConfirm): boolean {
  const button = el.closest("button") ?? el;
  if (!CONFIRM_TEXT.test(visibleText(button))) return false;
  if ((button.getAttribute("type") ?? "").toLowerCase() === "submit") return false;
  if (kind === "date_picker") {
    return !!button.closest('[class*="date-picker__btn-wrap"]') && !!button.closest('[class*="date-picker__popup"],[class*="date-picker__panel-wrap"]');
  }
  return !!button.closest('[class*="product-selector"],[class*="productSelector"]') && !!button.closest('[class*="modal__footer"]');
}

/** Presses the date picker's / product picker's OWN confirm; false (nothing pressed) for anything else. */
export function pressOwnConfirm(el: HTMLElement, kind: OwnConfirm): boolean {
  if (!ownConfirmOf(el, kind)) return false;
  (el.closest("button") ?? el).click();
  return true;
}

// -- finding a labelled row ----------------------------------------------------------------

const CONTROLISH = [
  "input",
  "textarea",
  "select",
  '[role="radio"]',
  '[role="combobox"]',
  '[role="switch"]',
  '[class*="eds-selector"]',
  '[class*="eds-radio"]',
  '[class*="eds-switch"]',
].join(",");

/** The nearest ancestor of the label text that holds a control; null if the label is absent or twice. */
export function findRow(doc: Document, label: string, within?: Element): HTMLElement | null {
  const wanted = normalizeLabel(label);
  const root: ParentNode = within ?? doc.body;
  const labels = Array.from(root.querySelectorAll("*")).filter((el) => {
    if (el.tagName === "SCRIPT" || el.tagName === "STYLE" || !usable(el)) return false;
    let own = "";
    for (const n of Array.from(el.childNodes)) if (n.nodeType === 3) own += n.nodeValue ?? "";
    return normalizeLabel(own) === wanted;
  });
  const rows = new Set<HTMLElement>();
  for (const l of labels) {
    for (let scope: Element | null = l, depth = 0; scope && depth < 6; scope = scope.parentElement, depth += 1) {
      if (scope !== l && Array.from(scope.querySelectorAll(CONTROLISH)).some(usable)) {
        rows.add(scope as HTMLElement);
        break;
      }
    }
  }
  return rows.size === 1 ? ([...rows][0] as HTMLElement) : null;
}

async function waitFor<T>(env: Env, find: () => T | null | undefined, ms = WAIT_MS): Promise<T | null> {
  const until = env.now() + ms;
  for (;;) {
    const found = find();
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(POLL_MS);
  }
}

export function textBoxesIn(row: Element): HTMLInputElement[] {
  return Array.from(row.querySelectorAll<HTMLInputElement>('input:not([type]),input[type="text"],input[type="number"],input[type="tel"]')).filter(
    (i) => usable(i) && !i.disabled && !i.readOnly,
  );
}

// -- text and numbers ---------------------------------------------------------------------

/**
 * Types `value` into a text box the way a person would (core writeValue: native setter + input /
 * change), keeping the value it held before (for the revert) and recording the write so the job
 * runner reads it again later. True when it reads back equal right now.
 */
export function writeBox(env: Env, box: HTMLInputElement, value: string): boolean {
  const key = env.log?.keyOf(env);
  if (env.log && key) {
    env.log.captureBefore(key, box.value);
    env.log.wrote({ key, el: box, want: value, seen: () => box.value, ok: () => box.value === value, rewrite: () => writeValue(box, value) });
  }
  // 0.3.27 (combo form, 2026-11-18): Shopee validates a box on focus / blur, as when a person tabs through
  box.focus();
  const ok = writeValue(box, value) && box.value === value;
  box.blur();
  return ok && mark(box);
}

/** Types into the `index`-th text box of the labelled row; true when it reads back equal. */
export function setRowText(env: Env, label: string, value: string, index = 0, within?: Element): boolean {
  const row = findRow(env.doc, label, within);
  const box = row ? textBoxesIn(row)[index] : undefined;
  if (!box) return false;
  return writeBox(env, box, value);
}

/** Records a pressed choice (radio / select / switch) for the re-read; never pressed again. */
function recordChoice(env: Env, el: HTMLElement, want: string, before: string, seen: () => string, ok: () => boolean): void {
  const key = env.log?.keyOf(env);
  if (!env.log || !key) return;
  env.log.captureBefore(key, before.slice(0, MAX_BEFORE_CHARS));
  env.log.wrote({ key, el, want, seen, ok });
}

function mark(el: HTMLElement): true {
  el.style.outline = "2px solid #db2777";
  el.style.outlineOffset = "2px";
  el.setAttribute("data-juli-filled", "1");
  return true;
}

// -- radio ----------------------------------------------------------------------------------

function isChecked(el: Element): boolean {
  const input = el.matches("input") ? (el as HTMLInputElement) : el.querySelector<HTMLInputElement>('input[type="radio"],input[type="checkbox"]');
  if (input) return input.checked;
  const aria = el.getAttribute("aria-checked") ?? el.querySelector("[aria-checked]")?.getAttribute("aria-checked");
  if (aria) return aria === "true";
  return /(checked|selected|active)/.test(el.className.toString()) && !/unchecked/.test(el.className.toString());
}

/** The radio / switch option whose text is `option` (or one of its spellings) inside `row`. */
function optionIn(row: Element, option: string | readonly string[]): HTMLElement | null {
  const wanted = (typeof option === "string" ? [option] : option).map(normalizeLabel);
  const hits = Array.from(row.querySelectorAll<HTMLElement>("label,span,div,li,button")).filter(
    (el) => usable(el) && wanted.includes(visibleText(el)),
  );
  // the innermost match is the clickable option
  return hits.find((h) => !hits.some((o) => o !== h && h.contains(o))) ?? null;
}

/** The text of the checked option of a radio group ("" when none is checked). */
function checkedText(row: Element): string {
  const all = [...(row.matches("label,[role='radio']") ? [row as HTMLElement] : []), ...Array.from(row.querySelectorAll<HTMLElement>("label,[role='radio']"))];
  const holders = all.filter((h) => usable(h) && isChecked(h));
  const inner = holders.filter((h) => !holders.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (inner[0]!.textContent ?? "").trim() : "";
}

/**
 * Chooses the radio `option` (any of its spellings) in the group labelled `label`. 0.3.27 (E45):
 * ✓ only when the group's ONE checked option reads as that option; a group whose checked option
 * cannot be read ("") is never ✓.
 */
export async function chooseRadio(env: Env, label: string, option: string | readonly string[], within?: Element): Promise<boolean> {
  const row = findRow(env.doc, label, within);
  if (!row) return false;
  const target = optionIn(row, option);
  if (!target) return false;
  const names = (typeof option === "string" ? [option] : option).map(normalizeLabel);
  const holder = target.closest("label") ?? target;
  const chosen = () => checkedText(row);
  const holds = () => isChecked(holder) && names.includes(normalizeLabel(chosen()));
  recordChoice(env, holder as HTMLElement, typeof option === "string" ? option : option[0]!, chosen(), chosen, holds);
  if (!holds() && !press(holder as HTMLElement)) return false;
  const ok = await waitFor(env, () => (holds() ? true : null), 1_000);
  if (ok) mark(holder as HTMLElement);
  return !!ok;
}

// -- select ---------------------------------------------------------------------------------

/** Opens the select labelled `label` and picks the option with that exact text. */
export async function chooseSelect(env: Env, label: string, option: string, index = 0, within?: Element): Promise<boolean> {
  const row = findRow(env.doc, label, within);
  if (!row) return false;
  const wanted = normalizeLabel(option);
  const native = Array.from(row.querySelectorAll<HTMLSelectElement>("select")).filter(usable)[index];
  if (native) {
    const hit = Array.from(native.options).find((o) => normalizeLabel(o.text) === wanted);
    if (!hit) return false;
    recordChoice(env, native, option, native.selectedOptions[0]?.text ?? "", () => native.selectedOptions[0]?.text ?? "", () => native.value === hit.value);
    const win = env.doc.defaultView!;
    const setter = Object.getOwnPropertyDescriptor(win.HTMLSelectElement.prototype, "value")?.set;
    if (setter) setter.call(native, hit.value);
    else native.value = hit.value;
    native.dispatchEvent(new win.Event("input", { bubbles: true }));
    native.dispatchEvent(new win.Event("change", { bubbles: true }));
    return native.value === hit.value && mark(native);
  }
  const selector = Array.from(row.querySelectorAll<HTMLElement>('[class*="eds-selector"],[role="combobox"]'))
    .filter(usable)
    .filter((el) => !el.parentElement?.closest('[class*="eds-selector"],[role="combobox"]'))[index];
  if (!selector) return false;
  recordChoice(env, selector, option, (selector.textContent ?? "").trim(), () => (selector.textContent ?? "").trim(), () => visibleText(selector).includes(wanted));
  if (visibleText(selector) === wanted) return mark(selector);
  if (!press(selector)) return false;
  const choice = await waitFor(env, () => {
    // the options are drawn in a popper that may sit outside the row
    const opts = Array.from(env.doc.querySelectorAll<HTMLElement>('[role="option"],[class*="eds-option"],[class*="eds-dropdown-item"],li')).filter(
      (o) => usable(o) && visibleText(o) === wanted && !selector.contains(o),
    );
    return opts.length === 1 ? opts[0] : null;
  });
  if (!choice || !press(choice)) return false;
  const shown = await waitFor(env, () => (visibleText(selector).includes(wanted) ? true : null), 1_500);
  return !!shown && mark(selector);
}

// -- date and time -------------------------------------------------------------------------

/** `HH:mm DD-MM-YYYY`, the format Seller Centre's pickers show and accept. */
export const DATE_FORMAT = /^([01]\d|2[0-3]):[0-5]\d (0[1-9]|[12]\d|3[01])-(0[1-9]|1[0-2])-\d{4}$/;

/** The date inputs of a labelled period row (Shopee draws them read-only: they open the picker). */
function dateInputs(row: Element): HTMLInputElement[] {
  return Array.from(row.querySelectorAll<HTMLInputElement>('input:not([type]),input[type="text"]')).filter(
    (i) => usable(i) && !i.disabled && (/\d{2}:\d{2}|DD|MM|YYYY|Chọn|ngày|thời gian|select date/i.test(`${i.placeholder} ${i.value}`) || !!i.closest('[class*="date"],[class*="picker"]')),
  );
}

/** The open date-time picker popover (the newest one drawn), or null. */
export function datePopup(env: Env): HTMLElement | null {
  const pops = Array.from(env.doc.querySelectorAll<HTMLElement>('[class*="date-picker__popup"]')).filter(usable);
  return pops.length > 0 ? (pops[pops.length - 1] as HTMLElement) : null;
}

const MONTH_OF = (text: string): number | null => {
  const m = /(\d{1,2})/.exec(text);
  const n = m ? Number(m[1]) : NaN;
  return n >= 1 && n <= 12 ? n : null;
};

/** The header's month / year ("Th11" "2026"), or null when it cannot be read. */
function shownMonth(pop: Element): { month: number; year: number } | null {
  const month = pop.querySelector('[class*="date-box"] [class*="month"]')?.textContent ?? "";
  const year = pop.querySelector('[class*="date-box"] [class*="year"]')?.textContent ?? "";
  const m = MONTH_OF(month);
  const y = /^\s*(\d{4})\s*$/.exec(year)?.[1];
  return m && y ? { month: m, year: Number(y) } : null;
}

/** The header arrows in drawn order: [prev year, prev month, next month, next year]. */
function arrows(pop: Element): { prevMonth?: HTMLElement; nextMonth?: HTMLElement } {
  const header = pop.querySelector('[class*="date-picker__header"]');
  if (!header) return {};
  const all = Array.from(header.querySelectorAll<HTMLElement>('[class*="btn-arrow"]')).filter(usable);
  const single = all.filter((a) => !/\bdouble\b/.test(a.className.toString()));
  return single.length === 2 ? { prevMonth: single[0], nextMonth: single[1] } : {};
}

/** The day cell `day` of the month shown (not a greyed day of the month before / after, not disabled). */
function dayCell(pop: Element, day: number): HTMLElement | null {
  const cells = Array.from(pop.querySelectorAll<HTMLElement>('[class*="date-picker__table-row"] [class*="date-picker__table-cell"]')).filter(
    (c) => !/table-cell-wrap/.test(c.className.toString()) && usable(c) && (c.textContent ?? "").trim() === String(day),
  );
  const own = cells.filter((c) => !/(prev|next|other|outside|last-month|next-month|not-current)/i.test(c.className.toString()));
  if (own.length === 0) return null;
  // the 6-week grid repeats a low day at its end (next month) and a high day at its start (last month)
  const cell = day >= 15 ? own[own.length - 1]! : own[0]!;
  return /\bdisabled\b/.test(cell.className.toString()) ? null : cell;
}

/** The hour (0) or minute (1) column's box with this two-digit text. */
function timeBox(pop: Element, column: 0 | 1, text: string): HTMLElement | null {
  const cols = Array.from(pop.querySelectorAll<HTMLElement>('[class*="time-picker__tp-scrollbar"]'));
  const col = cols[column];
  if (!col || cols.length !== 2) return null;
  const hits = Array.from(col.querySelectorAll<HTMLElement>('[class*="time-box"]')).filter((b) => (b.textContent ?? "").trim() === text);
  return hits.length === 1 ? (hits[0] as HTMLElement) : null;
}

/**
 * 0.3.27 (E41): sets the `index`-th date of the labelled row through Shopee's date-time picker:
 * open it (a press on the input), go to the month, press the day, the hour and the minute, then the
 * picker's OWN Xác nhận (never the form's). A page without the picker gets the value typed (older
 * builds). ✓ only when the input then shows exactly `value` (`HH:mm DD-MM-YYYY`).
 */
export async function setDate(env: Env, label: string, value: string, index: number, within?: Element): Promise<boolean> {
  const parts = /^(\d{2}):(\d{2}) (\d{2})-(\d{2})-(\d{4})$/.exec(value);
  if (!DATE_FORMAT.test(value) || !parts) return false;
  const row = findRow(env.doc, label, within);
  if (!row) return false;
  const box = dateInputs(row)[index];
  if (!box) return false;
  const key = env.log?.keyOf(env);
  if (env.log && key) {
    env.log.captureBefore(key, box.value);
    env.log.wrote({ key, el: box, want: value, seen: () => box.value, ok: () => box.value === value });
  }
  if (box.value === value) return mark(box);
  if (!box.readOnly && !datePopup(env)) {
    // no picker drawn yet: open it first; a page that never draws one takes the typed value
    box.focus();
    if (!press(box)) return false;
    const pop = await waitFor(env, () => datePopup(env), 1_000);
    if (!pop) {
      const typed = writeValue(box, value) && box.value === value;
      return typed && mark(box);
    }
  } else if (!datePopup(env)) {
    box.focus();
    if (!press(box)) return false;
  }
  const pop = await waitFor(env, () => datePopup(env), 2_000);
  if (!pop) return false;
  const [, hh, mm, dd, mo, yyyy] = parts as unknown as [string, string, string, string, string, string];
  const want = { month: Number(mo), year: Number(yyyy) };
  for (let guard = 0; guard < 36; guard += 1) {
    const shown = shownMonth(pop);
    if (!shown) return false;
    const diff = (want.year - shown.year) * 12 + (want.month - shown.month);
    if (diff === 0) break;
    const { prevMonth, nextMonth } = arrows(pop);
    const arrow = diff > 0 ? nextMonth : prevMonth;
    if (!arrow || !press(arrow)) return false;
    const moved = await waitFor(env, () => {
      const now = shownMonth(pop);
      return now && (now.month !== shown.month || now.year !== shown.year) ? true : null;
    }, 1_000);
    if (!moved) return false;
  }
  const cell = dayCell(pop, Number(dd));
  if (!cell || !press(cell)) return false;
  const hour = await waitFor(env, () => timeBox(pop, 0, hh), 1_000);
  if (!hour || !press(hour)) return false;
  const minute = await waitFor(env, () => timeBox(pop, 1, mm), 1_000);
  if (!minute || !press(minute)) return false;
  const confirm = Array.from(pop.querySelectorAll<HTMLElement>('[class*="date-picker__btn-wrap"] button')).find((b) => ownConfirmOf(b, "date_picker"));
  if (!confirm || !pressOwnConfirm(confirm, "date_picker")) return false;
  const shown = await waitFor(env, () => (box.value === value ? true : null), 1_500);
  return !!shown && mark(box);
}

// -- switch ---------------------------------------------------------------------------------

export async function setSwitch(env: Env, label: string, on: boolean): Promise<boolean> {
  const row = findRow(env.doc, label);
  const sw = row ? Array.from(row.querySelectorAll<HTMLElement>('[role="switch"],[class*="eds-switch"],input[type="checkbox"]')).find(usable) : undefined;
  if (!sw) return false;
  const state = () => (sw.matches("input") ? (sw as HTMLInputElement).checked : sw.getAttribute("aria-checked") === "true" || /(open|checked|on)\b/.test(sw.className.toString()));
  const shown = () => (state() ? "bật" : "tắt");
  recordChoice(env, sw, on ? "bật" : "tắt", shown(), shown, () => state() === on);
  if (state() !== on && !press(sw)) return false;
  return !!(await waitFor(env, () => (state() === on ? true : null), 1_000)) && mark(sw);
}

// -- repeated rows ("Thêm mức ưu đãi") -----------------------------------------------------

/** The visible button with this text (own text only), or null if none / more than one. */
export function findPressable(env: Env, text: string, within?: Element): HTMLElement | null {
  const wanted = normalizeLabel(text);
  const root: ParentNode = within ?? env.doc.body;
  const hits = Array.from(root.querySelectorAll<HTMLElement>("button,[role='button'],[role='menuitem'],a,li,span,div")).filter(
    (el) => usable(el) && visibleText(el) === wanted && el.children.length <= 2,
  );
  const inner = hits.filter((h) => !hits.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (inner[0] as HTMLElement) : null;
}

/** Presses `addLabel` until `have()` reaches `count`, waiting for each new row to appear. */
export async function ensureCount(env: Env, addLabel: string, have: () => number, count: number): Promise<boolean> {
  for (let guard = 0; guard < 12 && have() < count; guard += 1) {
    const before = have();
    const add = findPressable(env, addLabel);
    if (!add || !press(add)) return false;
    if (!(await waitFor(env, () => (have() > before ? true : null), 1_500))) return false;
  }
  return have() >= count;
}

/** Presses `addLabel` until `count` rows (elements matched by `rowSelector`) exist. */
export function ensureRows(env: Env, addLabel: string, rowSelector: string, count: number): Promise<boolean> {
  return ensureCount(env, addLabel, () => Array.from(env.doc.querySelectorAll<HTMLElement>(rowSelector)).filter(usable).length, count);
}

// -- product picker (modal) ----------------------------------------------------------------

/** The open dialog that holds a search box (the product picker), or null. */
export function pickerModal(env: Env): HTMLElement | null {
  const dialogs = Array.from(env.doc.querySelectorAll<HTMLElement>('[role="dialog"],[class*="eds-modal"],[class*="modal"]')).filter(usable);
  const withSearch = dialogs.filter((d) => textBoxesIn(d).length > 0);
  const inner = withSearch.filter((h) => !withSearch.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (inner[0] as HTMLElement) : null;
}

export interface PickResult {
  ticked: string[];
  missing: string[];
  /** The picker's own Xác nhận was pressed and the dialog closed (0.3.27). */
  confirmed?: boolean;
  /** Why nothing could be ticked (Vietnamese, for the panel), when the picker itself failed. */
  reason?: string;
}

export const PICK_NO_OPENER = "Không thấy nút «Thêm sản phẩm» trên trang";
export const PICK_NO_MODAL = "Hộp chọn sản phẩm không mở";
export const PICK_NO_SEARCH = "Hộp chọn sản phẩm không có ô tìm";
export const pickNotFound = (ids: readonly string[]) => `Tìm theo ID không ra đúng một dòng: ${ids.join(", ")}`;

/** A leaf of the row shows this item id as a whole number ("ID: 1001", not "10012"). */
export function holdsId(row: Element, id: string): boolean {
  const re = new RegExp(`(^|\\D)${id}(\\D|$)`);
  return [row, ...Array.from(row.querySelectorAll("*"))].some((el) => el.children.length === 0 && re.test(el.textContent ?? ""));
}

const CHECKBOX = 'input[type="checkbox"],[role="checkbox"],[class*="eds-checkbox"]';

export const PICK_NO_ID_MODE = "Không chuyển được ô tìm sang «Mã sản phẩm»";
export const PICK_NOT_CONFIRMED = "Chưa bấm được Xác nhận của hộp chọn sản phẩm";
const ID_MODE = /^(mã sản phẩm|product id|id sản phẩm)$/;

/**
 * 0.3.27 (E48): the picker's search type. The live dialog has a select in front of the search box
 * ("Tên sản phẩm" | "Mã sản phẩm"); an id typed under "Tên sản phẩm" finds other products. True when
 * the box now searches by id, or when the dialog has no such select (one box for name or id).
 */
export async function searchById(env: Env, modal: HTMLElement): Promise<boolean> {
  const select = Array.from(modal.querySelectorAll<HTMLElement>('[class*="input-group__prepend"] [class*="select"]')).filter(usable)[0];
  if (!select) return true;
  const shows = () => ID_MODE.test(visibleText(select));
  if (shows()) return true;
  if (!press(select)) return false;
  const option = await waitFor(env, () => {
    const opts = Array.from(env.doc.querySelectorAll<HTMLElement>('[class*="select-option"]')).filter(
      (o) => usable(o) && ID_MODE.test(visibleText(o)) && !/select-options-list/.test(o.className.toString()),
    );
    return opts.length >= 1 ? opts[opts.length - 1] : null;
  }, 1_500);
  if (!option || !press(option)) return false;
  return !!(await waitFor(env, () => (shows() ? true : null), 1_500));
}

/** The picker's search text box: the one after the search-type select, else the dialog's first. */
function searchBox(modal: HTMLElement): HTMLInputElement | undefined {
  const appended = Array.from(modal.querySelectorAll<HTMLInputElement>('[class*="input-group__append"] input')).filter((i) => usable(i) && !i.disabled);
  return appended[0] ?? textBoxesIn(modal)[0];
}

/**
 * Opens "Thêm sản phẩm", switches the search to the product id, searches each id and ticks its
 * row. With `confirm`, then presses the PICKER's own Xác nhận (owner, 2026-11-18: allowed, it is
 * not the form's save) and checks the form lists every id. Every tick is recorded under the env's
 * field key (re-read later: a product that is no longer chosen turns the step ✗).
 */
export async function pickProducts(env: Env, opener: string, ids: readonly string[], opts: { confirm?: boolean } = {}): Promise<PickResult> {
  const out: PickResult = { ticked: [], missing: [...ids] };
  if (!pickerModal(env)) {
    const open = await waitFor(env, () => findPressable(env, opener));
    if (!open || !press(open)) return { ...out, reason: PICK_NO_OPENER };
  }
  const modal = await waitFor(env, () => pickerModal(env));
  if (!modal) return { ...out, reason: PICK_NO_MODAL };
  const checks: HTMLElement[] = [];
  if (!(await searchById(env, modal))) return { ...out, reason: PICK_NO_ID_MODE };
  for (const id of ids) {
    const search = searchBox(modal);
    if (!search) return { ...out, reason: PICK_NO_SEARCH };
    if (!writeValue(search, id)) continue;
    const go = findPressable(env, "Tìm kiếm", modal) ?? findPressable(env, "Tìm", modal);
    if (go) press(go);
    const box = await waitFor(env, () => {
      const rows = Array.from(modal.querySelectorAll<HTMLElement>("tr,li,[class*='row'],[role='row']")).filter(
        (r) => usable(r) && holdsId(r, id) && r.querySelector(CHECKBOX),
      );
      const inner = rows.filter((h) => !rows.some((o) => o !== h && h.contains(o)));
      return inner.length === 1 ? (inner[0] as HTMLElement) : null;
    });
    if (!box) continue;
    const check = box.querySelector<HTMLElement>(CHECKBOX)!;
    if (!ticked(check) && !press(check)) continue;
    if (await waitFor(env, () => (ticked(check) ? true : null), 1_000)) {
      out.ticked.push(id);
      out.missing = out.missing.filter((m) => m !== id);
      checks.push(check);
      mark(box);
    }
  }
  const key = env.log?.keyOf(env);
  let confirmed = false;
  if (opts.confirm && out.missing.length === 0 && checks.length > 0) {
    // the search sits in the dialog's body; its own footer is on the `.product-selector` frame
    const frame = modal.closest<HTMLElement>('[class*="product-selector"],[class*="productSelector"]') ?? modal;
    const footer = Array.from(frame.querySelectorAll<HTMLElement>('[class*="modal__footer"] button')).find((b) => ownConfirmOf(b, "product_picker"));
    // an older dialog without that footer: the person confirms (the panel says so)
    if (footer) {
      confirmed = pressOwnConfirm(footer, "product_picker") && !!(await waitFor(env, () => (!env.doc.contains(frame) || hidden(frame) ? true : null), 2_000));
      if (!confirmed) out.reason = PICK_NOT_CONFIRMED;
      out.confirmed = confirmed;
    }
  }
  /** The form (outside the dialog) lists the product: its row shows the id. */
  const listed = (id: string) =>
    Array.from(env.doc.querySelectorAll<HTMLElement>("tr,li,[class*='row'],[role='row']")).some((r) => usable(r) && !r.closest('[role="dialog"],[class*="modal"]') && holdsId(r, id));
  if (env.log && key && checks.length > 0) {
    env.log.wrote({
      key,
      el: confirmed ? env.doc.body : modal,
      want: `${checks.length} sản phẩm`,
      seen: () =>
        (confirmed ? `${ids.filter(listed).length} sản phẩm trong combo/voucher` : `${checks.filter(ticked).length} sản phẩm đã tick`) +
        (out.missing.length > 0 ? `, thiếu ID ${out.missing.join(", ")}` : ""),
      // every product of the card, not only those ticked (a re-read never turns a missing one ✓)
      ok: () => out.missing.length === 0 && (confirmed ? ids.every(listed) : checks.every((c) => env.doc.contains(c) && ticked(c))),
    });
  }
  if (out.missing.length > 0 && !out.reason) out.reason = pickNotFound(out.missing);
  return out;
}

function ticked(check: HTMLElement): boolean {
  if (check.matches("input")) return (check as HTMLInputElement).checked;
  const aria = check.getAttribute("aria-checked");
  if (aria !== null) return aria === "true";
  const input = check.querySelector<HTMLInputElement>('input[type="checkbox"]');
  if (input) return input.checked;
  return /(checked|selected)/.test(check.className.toString()) && !/unchecked/.test(check.className.toString());
}

/** The innermost control in `row` whose whole text is one of `texts` (lowercase), or null. Never pressed here. */
export function controlWithText(row: Element, texts: ReadonlySet<string>): HTMLElement | null {
  const hits = Array.from(row.querySelectorAll<HTMLElement>("button,a,span,div,[role='button']")).filter((el) => usable(el) && texts.has(visibleText(el)));
  const inner = hits.filter((h) => !hits.some((o) => o !== h && h.contains(o)));
  return inner[0] ?? null;
}

// -- notices that cover the page ------------------------------------------------------------

/**
 * Shopee's own announcements that cover a page (live 2026-11-17: "Phiên bản Chiến dịch Mở Rộng
 * mới!" over the affiliate page). Only a dialog whose text matches one of these AND that holds no
 * text box (not a form) is closed: its close icon first, else a button that only dismisses.
 * Nothing that saves or confirms is ever pressed (press() still refuses those).
 */
export const KNOWN_NOTICES: readonly RegExp[] = [
  /phiên bản .{0,60}mới/,
  /tính năng mới/,
  /chiến dịch mở rộng mới/,
  /new open campaign version/,
  /new version/,
];
/** Shopee's feedback widget ("Thông tin góp ý … Quay màn hình khi gặp sự cố"): never a notice (E21). */
export const FEEDBACK_WIDGET = /(góp ý|quay màn hình|feedback|screen record)/;
/** Buttons that only dismiss. Never "Khám phá ngay" / "Explore now": that navigates (owner, 2026-11-18). */
const DISMISS_TEXTS = ["để sau", "bỏ qua", "đã hiểu", "tôi đã hiểu", "đóng", "close", "later", "got it"];
const CLOSE_ICON = '[aria-label*="close" i],[aria-label*="đóng" i],[class*="close"]';

function noticeDialogs(env: Env): HTMLElement[] {
  const all = Array.from(env.doc.querySelectorAll<HTMLElement>('[role="dialog"],[class*="eds-modal"],[class*="modal"]')).filter(usable);
  const hits = all.filter((d) => {
    const text = normalizeLabel(d.textContent ?? "");
    return KNOWN_NOTICES.some((re) => re.test(text)) && !FEEDBACK_WIDGET.test(text) && textBoxesIn(d).length === 0;
  });
  // the outermost dialog of a notice (its close icon sits on the frame)
  return hits.filter((h) => !hits.some((o) => o !== h && o.contains(h)));
}

/** Closes Shopee's known notices; the notes say which (for the panel). */
export async function dismissNotices(env: Env): Promise<string[]> {
  const notes: string[] = [];
  for (const dialog of noticeDialogs(env)) {
    const title = (dialog.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 50);
    const icons = Array.from(dialog.querySelectorAll<HTMLElement>(CLOSE_ICON)).filter(usable);
    const icon = icons.find((i) => !icons.some((o) => o !== i && i.contains(o)));
    let pressed = !!icon && press(icon);
    if (!pressed) {
      for (const text of DISMISS_TEXTS) {
        const button = findPressable(env, text, dialog);
        if (button && press(button)) {
          pressed = true;
          break;
        }
      }
    }
    if (!pressed) {
      notes.push(`Thông báo của Shopee «${title}» đang che trang; hãy tự đóng rồi mở lại từ Juli.`);
      continue;
    }
    const gone = await waitFor(env, () => (!env.doc.contains(dialog) || hidden(dialog) ? true : null), 2_000);
    notes.push(gone ? `Juli đã đóng thông báo của Shopee «${title}» (không bấm gì khác).` : `Thông báo của Shopee «${title}» chưa đóng được.`);
  }
  return notes;
}

// -- dialogs ---------------------------------------------------------------------------------

/** The open dialog whose heading text is `heading` (innermost), or null. */
export function findDialog(env: Env, heading: string): HTMLElement | null {
  const wanted = normalizeLabel(heading);
  const dialogs = Array.from(env.doc.querySelectorAll<HTMLElement>('[role="dialog"],[class*="eds-modal"],[class*="eds-popover"],[class*="modal"]')).filter(usable);
  const hits = dialogs.filter((d) =>
    Array.from(d.querySelectorAll("*")).some((el) => {
      let own = "";
      for (const n of Array.from(el.childNodes)) if (n.nodeType === 3) own += n.nodeValue ?? "";
      return normalizeLabel(own) === wanted;
    }),
  );
  const inner = hits.filter((h) => !hits.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (inner[0] as HTMLElement) : null;
}

/** The edit control (pencil) of a labelled card: aria-label / title "Chỉnh sửa", else its only pressable icon. */
export function findEditPencil(env: Env, label: string): HTMLElement | null {
  const row = findLabelCard(env, label) ?? findRow(env.doc, label);
  if (!row) return null;
  const marked = Array.from(row.querySelectorAll<HTMLElement>('[aria-label*="chỉnh sửa" i],[title*="chỉnh sửa" i],[class*="pencil"],[class*="edit"]')).filter(usable);
  const inner = marked.filter((h) => !marked.some((o) => o !== h && h.contains(o)));
  if (inner.length === 1) return inner[0] as HTMLElement;
  const buttons = Array.from(row.querySelectorAll<HTMLElement>("button,[role='button']")).filter(usable);
  return buttons.length === 1 ? (buttons[0] as HTMLElement) : null;
}

/** A card whose heading is `label` and that holds a pressable (the row finder wants a control). */
function findLabelCard(env: Env, label: string): HTMLElement | null {
  const wanted = normalizeLabel(label);
  const heads = Array.from(env.doc.body.querySelectorAll("*")).filter((el) => {
    if (!usable(el)) return false;
    let own = "";
    for (const n of Array.from(el.childNodes)) if (n.nodeType === 3) own += n.nodeValue ?? "";
    return normalizeLabel(own) === wanted;
  });
  if (heads.length !== 1) return null;
  for (let scope: Element | null = heads[0] as Element, depth = 0; scope && depth < 5; scope = scope.parentElement, depth += 1) {
    if (scope !== heads[0] && Array.from(scope.querySelectorAll("button,[role='button'],[aria-label],[class*='pencil'],[class*='edit']")).some(usable)) return scope as HTMLElement;
  }
  return null;
}
