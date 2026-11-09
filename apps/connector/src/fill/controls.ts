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

import { normalizeLabel, PANEL_ID } from "./locate";
import { writeValue } from "./write";

export interface Env {
  doc: Document;
  sleep(ms: number): Promise<void>;
  now(): number;
}

export const WAIT_MS = 4_000;
const POLL_MS = 150;

/** Texts that end in Shopee saving, sending, confirming, deleting or cancelling something. */
export const FORBIDDEN_PRESS =
  /^(lưu|lưu lại|lưu ở dạng nháp|xác nhận|gửi|gửi đi|cập nhật|tạo|tạo mới|đăng|xóa|loại bỏ|hủy|ẩn|áp dụng|hoàn tất|đồng ý|submit|save|confirm|send|delete)$/;

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

/** The single place the fill code presses something. Returns false (and presses nothing) when unsafe. */
export function press(el: HTMLElement): boolean {
  if (unsafePress(el) !== null) return false;
  el.click();
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

/** Types into the `index`-th text box of the labelled row; true when it reads back equal. */
export function setRowText(env: Env, label: string, value: string, index = 0, within?: Element): boolean {
  const row = findRow(env.doc, label, within);
  const box = row ? textBoxesIn(row)[index] : undefined;
  if (!box) return false;
  return writeValue(box, value) && box.value === value && mark(box);
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

/** The radio / switch option whose text is `option` inside `row`. */
function optionIn(row: Element, option: string): HTMLElement | null {
  const wanted = normalizeLabel(option);
  const hits = Array.from(row.querySelectorAll<HTMLElement>("label,span,div,li,button")).filter(
    (el) => usable(el) && visibleText(el) === wanted,
  );
  // the innermost match is the clickable option
  return hits.find((h) => !hits.some((o) => o !== h && h.contains(o))) ?? null;
}

/** Chooses the radio `option` in the group labelled `label`; verifies it reads back checked. */
export async function chooseRadio(env: Env, label: string, option: string, within?: Element): Promise<boolean> {
  const row = findRow(env.doc, label, within);
  if (!row) return false;
  const target = optionIn(row, option);
  if (!target) return false;
  const holder = target.closest("label") ?? target;
  if (!isChecked(holder) && !press(holder as HTMLElement)) return false;
  const ok = await waitFor(env, () => (isChecked(holder) ? true : null), 1_000);
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

/** Types a date into the `index`-th picker input of the labelled row; verifies what is displayed. */
export function setDate(env: Env, label: string, value: string, index: number, within?: Element): boolean {
  if (!DATE_FORMAT.test(value)) return false;
  const row = findRow(env.doc, label, within);
  if (!row) return false;
  const inputs = textBoxesIn(row).filter((i) => /\d{2}:\d{2}|DD|MM|YYYY|Chọn|ngày|thời gian/i.test(`${i.placeholder} ${i.value}`) || i.closest('[class*="date"],[class*="picker"]'));
  const box = inputs[index];
  if (!box) return false;
  return writeValue(box, value) && box.value === value && mark(box);
}

// -- switch ---------------------------------------------------------------------------------

export async function setSwitch(env: Env, label: string, on: boolean): Promise<boolean> {
  const row = findRow(env.doc, label);
  const sw = row ? Array.from(row.querySelectorAll<HTMLElement>('[role="switch"],[class*="eds-switch"],input[type="checkbox"]')).find(usable) : undefined;
  if (!sw) return false;
  const state = () => (sw.matches("input") ? (sw as HTMLInputElement).checked : sw.getAttribute("aria-checked") === "true" || /(open|checked|on)\b/.test(sw.className.toString()));
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
}

/**
 * Opens "Thêm sản phẩm", searches each product by ID and ticks its row. It does NOT press the
 * dialog's own Xác nhận: the person confirms the selection, then Shopee's save.
 */
export async function pickProducts(env: Env, opener: string, ids: readonly string[]): Promise<PickResult> {
  const out: PickResult = { ticked: [], missing: [...ids] };
  if (!pickerModal(env)) {
    const open = findPressable(env, opener);
    if (!open || !press(open)) return out;
  }
  const modal = await waitFor(env, () => pickerModal(env));
  if (!modal) return out;
  for (const id of ids) {
    const search = textBoxesIn(modal)[0];
    if (!search || !writeValue(search, id)) continue;
    const go = findPressable(env, "Tìm kiếm", modal) ?? findPressable(env, "Tìm", modal);
    if (go) press(go);
    const box = await waitFor(env, () => {
      const rows = Array.from(modal.querySelectorAll<HTMLElement>("tr,li,[class*='row'],[role='row']")).filter(
        (r) => usable(r) && (r.textContent ?? "").includes(id) && r.querySelector('input[type="checkbox"],[role="checkbox"],[class*="eds-checkbox"]'),
      );
      const inner = rows.filter((h) => !rows.some((o) => o !== h && h.contains(o)));
      return inner.length === 1 ? (inner[0] as HTMLElement) : null;
    });
    if (!box) continue;
    const check = box.querySelector<HTMLElement>('input[type="checkbox"],[role="checkbox"],[class*="eds-checkbox"]')!;
    const on = () => (check.matches("input") ? (check as HTMLInputElement).checked : check.getAttribute("aria-checked") === "true");
    if (!on() && !press(check)) continue;
    if (await waitFor(env, () => (on() ? true : null), 1_000)) {
      out.ticked.push(id);
      out.missing = out.missing.filter((m) => m !== id);
      mark(box);
    }
  }
  return out;
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
