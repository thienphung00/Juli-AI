// The controls a fill job needs beyond a text box (P97 D85.6): radios, selects, date pickers,
// switches, repeated rows and a product picker. Shopee's `eds-react-*` components are found by the
// VISIBLE LABEL next to them, never by class name alone. Anything unclear (no row, a label twice,
// no such option) is "missing" and nothing is touched.
//
// 0.3.28 (F5.1, owner 2026-11-19): the Connector NEVER clicks on a Shopee page. Twice on 19/11 the
// voucher fill's element.click() (isTrusted=false) sent the tab to /verify/traffic/error; the
// title / description fills, value writes only, passed. So it writes values into text / number
// boxes only (native setter + input / change, core/fill/write.ts) and never clicks, focuses or
// dispatches a mouse / pointer / keyboard / focus event. Every control that needs a click is a
// GUIDED step: the control is highlighted, the panel says exactly what to choose, and the step
// turns ✓ only once the form shows it (the job runner's re-check). A box the person's click
// reveals (a tier row, the rate editor, the picker's search) is written on the next re-check.

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
/** Shown on the page and outside Juli's panel. */
export const usable = (el: Element) => !inPanel(el) && !hidden(el);

/** Why a control must never be highlighted as a step to press for the person (a save / confirm / send). */
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

/**
 * 0.3.28: what a click-needing control is after the fill: the form already shows the card's value
 * ("done"), the person has a step to do there and the control is highlighted ("todo"), or the
 * control is not on the page ("missing").
 */
export type Guide = "done" | "todo" | "missing";

/** Highlights a control the person clicks (the fill's mark style); never clicks it. */
export function highlight(target: HTMLElement): void {
  // the button the text sits in (findPressable returns the innermost text holder)
  const el = (target.closest("button,[role='button']") as HTMLElement | null) ?? target;
  el.style.outline = "2px dashed #db2777";
  el.style.outlineOffset = "2px";
  el.setAttribute("data-juli-guide", "1");
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

export async function waitFor<T>(env: Env, find: () => T | null | undefined, ms = WAIT_MS): Promise<T | null> {
  const until = env.now() + ms;
  for (;;) {
    const found = find();
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(POLL_MS);
  }
}

export function textBoxesIn(row: Element): HTMLInputElement[] {
  // a2 (capture c2/01, 23/11): Shopee's number boxes carry type="numeric" (combo tier quantity, Giới hạn đặt hàng): E116
  return Array.from(row.querySelectorAll<HTMLInputElement>('input:not([type]),input[type="text"],input[type="number"],input[type="tel"],input[type="numeric"]')).filter(
    (i) => usable(i) && !i.disabled && !i.readOnly,
  );
}

// -- text and numbers ---------------------------------------------------------------------

/**
 * Types `value` into a text box the way a person would (core writeValue: native setter + input /
 * change), keeping the value it held before (for the revert) and recording the write so the job
 * runner reads it again later. True when it reads back equal right now.
 */
/**
 * Hardening (E72 / E146; not the cause of the live ✗, see chooseSelect): a whole number the page shows with its own formatting ("2.000", "2,000", "₫ 2000",
 * "2 000") is the same number. Anything else (text, decimals) must be equal as typed.
 */
export function sameBoxValue(seen: string, want: string): boolean {
  if (seen === want) return true;
  if (!/^\d+$/.test(want)) return false;
  const shown = seen.replace(/[\s.,₫đĐ]/g, "");
  return shown !== "" && /^\d+$/.test(shown) && /^[\d\s.,₫đĐ]+$/.test(seen) && BigInt(shown) === BigInt(want);
}

export function writeBox(env: Env, box: HTMLInputElement, value: string): boolean {
  // a greyed (locked) box is never written (batch-1123-a D6)
  if (box.disabled || box.readOnly) return false;
  const key = env.log?.keyOf(env);
  if (env.log && key) {
    env.log.captureBefore(key, box.value);
    env.log.wrote({ key, el: box, want: value, seen: () => box.value, ok: () => sameBoxValue(box.value, value), rewrite: () => writeValue(box, value) });
  }
  // 0.3.28 (F5.1): no focus / blur any more (a focus event is a UI event): the value write only
  writeValue(box, value);
  return sameBoxValue(box.value, value) && mark(box);
}

/** Types into the `index`-th text box of the labelled row; true when it reads back equal. */
export function setRowText(env: Env, label: string, value: string, index = 0, within?: Element): boolean {
  const row = findRow(env.doc, label, within);
  const box = row ? textBoxesIn(row)[index] : undefined;
  if (!box) return false;
  return writeBox(env, box, value);
}

/** Records a choice (radio / select / switch) for the re-read: ✓ once the form shows it. */
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

/** The option `option` of the radio group labelled `label`, with whether the group shows it chosen. */
export function radioOf(doc: Document, label: string, option: string | readonly string[], within?: Element): { holder: HTMLElement; holds: () => boolean; chosen: () => string } | null {
  const row = findRow(doc, label, within);
  if (!row) return null;
  const target = optionIn(row, option);
  if (!target) return null;
  const names = (typeof option === "string" ? [option] : option).map(normalizeLabel);
  const holder = (target.closest("label") ?? target) as HTMLElement;
  const chosen = () => checkedText(row);
  return { holder, chosen, holds: () => isChecked(holder) && names.includes(normalizeLabel(chosen())) };
}

/** The options of the radio group labelled `label` as the page draws them (text and holder), outermost duplicates dropped. */
export function radioOptions(doc: Document, label: string): { text: string; holder: HTMLElement }[] {
  const row = findRow(doc, label);
  if (!row) return [];
  const all = Array.from(row.querySelectorAll<HTMLElement>("label,[role='radio']")).filter((h) => usable(h) && (h.textContent ?? "").trim() !== "");
  const inner = all.filter((h) => !all.some((o) => o !== h && h.contains(o)));
  return inner.map((h) => ({ text: (h.textContent ?? "").trim(), holder: h }));
}

/**
 * The radio `option` (any of its spellings) in the group labelled `label`: "done" when the group's
 * ONE checked option reads as that option (E45), else the option is highlighted for the person.
 */
export function chooseRadio(env: Env, label: string, option: string | readonly string[], within?: Element): Guide {
  const radio = radioOf(env.doc, label, option, within);
  if (!radio) return "missing";
  recordChoice(env, radio.holder, typeof option === "string" ? option : option[0]!, radio.chosen(), radio.chosen, radio.holds);
  if (radio.holds()) return mark(radio.holder) && "done";
  highlight(radio.holder);
  return "todo";
}

// -- select ---------------------------------------------------------------------------------

/** The row's visible text without its label's own words and without any input's value. */
function rowTextOutsideInputs(row: Element): string {
  const clone = row.cloneNode(true) as Element;
  clone.querySelectorAll("input,textarea,select,script,style").forEach((n) => n.remove());
  return normalizeLabel((clone.textContent ?? "").replace(/\s+/g, " "));
}

/**
 * The select labelled `label` on `option`: a native <select> takes the value (a value write); a
 * Shopee drop-down is "done" when it already shows the option, else highlighted for the person.
 */
export function chooseSelect(env: Env, label: string, option: string, index = 0, within?: Element, others: readonly string[] = []): Guide {
  const row = findRow(env.doc, label, within);
  if (!row) return "missing";
  const wanted = normalizeLabel(option);
  const native = Array.from(row.querySelectorAll<HTMLSelectElement>("select")).filter(usable)[index];
  if (native) {
    const hit = Array.from(native.options).find((o) => normalizeLabel(o.text) === wanted);
    if (!hit) return "missing";
    recordChoice(env, native, option, native.selectedOptions[0]?.text ?? "", () => native.selectedOptions[0]?.text ?? "", () => native.value === hit.value);
    const win = env.doc.defaultView!;
    const setter = Object.getOwnPropertyDescriptor(win.HTMLSelectElement.prototype, "value")?.set;
    if (setter) setter.call(native, hit.value);
    else native.value = hit.value;
    native.dispatchEvent(new win.Event("input", { bubbles: true }));
    native.dispatchEvent(new win.Event("change", { bubbles: true }));
    return native.value === hit.value ? mark(native) && "done" : "missing";
  }
  const selector = Array.from(row.querySelectorAll<HTMLElement>('[class*="eds-selector"],[role="combobox"]'))
    .filter(usable)
    .filter((el) => !el.parentElement?.closest('[class*="eds-selector"],[role="combobox"]'))[index];
  if (!selector) {
    // E146: the drop-down is not one Juli can identify. The row's own text (outside the boxes) is
    // read: exactly the wanted option and none of the others means the type is already right;
    // anything else is "missing" (a guided step of its own, never a ✗ on the amount beside it).
    const shown = () => rowTextOutsideInputs(row);
    const clear = () => shown().includes(wanted) && !others.map(normalizeLabel).some((o) => shown().includes(o));
    if (!clear()) return "missing";
    recordChoice(env, row, option, shown(), shown, clear);
    return "done";
  }
  const shows = () => visibleText(selector).includes(wanted);
  recordChoice(env, selector, option, (selector.textContent ?? "").trim(), () => (selector.textContent ?? "").trim(), shows);
  if (shows()) return mark(selector) && "done";
  highlight(selector);
  return "todo";
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

/** `HH:mm DD-MM-YYYY` as the person reads it in the step: `DD/MM/YYYY HH:mm`. */
export function dateText(value: string): string {
  const p = /^(\d{2}):(\d{2}) (\d{2})-(\d{2})-(\d{4})$/.exec(value);
  return p ? `${p[3]}/${p[4]}/${p[5]} ${p[1]}:${p[2]}` : value;
}

/**
 * The `index`-th date of the labelled row. 0.3.28: Shopee's picker input is read-only and opens a
 * picker that needs clicks, so it is the person's step (highlighted): "done" once the input shows
 * exactly `value` (`HH:mm DD-MM-YYYY`). An input that takes typing (older builds) gets the value.
 */
export function setDate(env: Env, label: string, value: string, index: number, within?: Element): Guide {
  if (!DATE_FORMAT.test(value)) return "missing";
  const row = findRow(env.doc, label, within);
  if (!row) return "missing";
  const box = dateInputs(row)[index];
  if (!box) return "missing";
  const key = env.log?.keyOf(env);
  if (env.log && key) {
    env.log.captureBefore(key, box.value);
    env.log.wrote({ key, el: box, want: value, seen: () => box.value, ok: () => box.value === value });
  }
  if (box.value === value) return mark(box) && "done";
  if (!box.readOnly && writeValue(box, value) && box.value === value) return mark(box) && "done";
  highlight(box);
  return "todo";
}

// -- switch ---------------------------------------------------------------------------------

/** The switch labelled `label`: "done" when it is already `on`, else highlighted for the person. */
export function setSwitch(env: Env, label: string, on: boolean): Guide {
  const row = findRow(env.doc, label);
  const sw = row ? Array.from(row.querySelectorAll<HTMLElement>('[role="switch"],[class*="eds-switch"],input[type="checkbox"]')).find(usable) : undefined;
  if (!sw) return "missing";
  const state = () => (sw.matches("input") ? (sw as HTMLInputElement).checked : sw.getAttribute("aria-checked") === "true" || /(open|checked|on)\b/.test(sw.className.toString()));
  const shown = () => (state() ? "bật" : "tắt");
  recordChoice(env, sw, on ? "bật" : "tắt", shown(), shown, () => state() === on);
  if (state() === on) return mark(sw) && "done";
  highlight(sw);
  return "todo";
}

// -- repeated rows ("Thêm mức ưu đãi") -----------------------------------------------------

/** The visible button with this text (own text only), or null if none / more than one. Found, never pressed. */
export function findPressable(env: Env, text: string, within?: Element): HTMLElement | null {
  const wanted = normalizeLabel(text);
  const root: ParentNode = within ?? env.doc.body;
  const hits = Array.from(root.querySelectorAll<HTMLElement>("button,[role='button'],[role='menuitem'],a,li,span,div")).filter(
    (el) => usable(el) && visibleText(el) === wanted && el.children.length <= 2,
  );
  const inner = hits.filter((h) => !hits.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (inner[0] as HTMLElement) : null;
}

/** The page's buttons whose text matches `text` (found to READ their state, never pressed). */
export function buttonsMatching(doc: Document, text: RegExp): HTMLButtonElement[] {
  return Array.from(doc.querySelectorAll<HTMLButtonElement>("button,[role='button']")).filter((b) => !inPanel(b) && text.test(b.textContent ?? ""));
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
  /** The form (outside the picker) lists every product of the card. */
  done: boolean;
  /** Why the step cannot even be guided (Vietnamese, for the panel). */
  reason?: string;
}

export const PICK_NO_OPENER = "Không thấy nút «Thêm sản phẩm» trên trang";

/** A leaf of the row shows this item id as a whole number ("ID: 1001", not "10012"). */
export function holdsId(row: Element, id: string): boolean {
  const re = new RegExp(`(^|\\D)${id}(\\D|$)`);
  return [row, ...Array.from(row.querySelectorAll("*"))].some((el) => el.children.length === 0 && re.test(el.textContent ?? ""));
}

const CHECKBOX = 'input[type="checkbox"],[role="checkbox"],[class*="eds-checkbox"]';

/** Shopee's selects (eds-react-select, custom-eds-react-select: capture c2/02); never "product-selector", the picker itself. */
const SELECT = '[class*="react-select"],[class*="eds-select"],[role="combobox"]';
/** A box of a select (its own type-to-search input), never the picker's search text box. */
const inSelect = (i: Element) => !!i.closest(SELECT);

/** The picker's search text box: the one after the search-type select, else the dialog's first that is not a select's. */
function searchBox(modal: HTMLElement): HTMLInputElement | undefined {
  const appended = Array.from(modal.querySelectorAll<HTMLInputElement>('[class*="input-group__append"] input')).filter((i) => usable(i) && !i.disabled && !inSelect(i));
  return appended[0] ?? textBoxesIn(modal).filter((i) => !inSelect(i))[0];
}

/** Shopee's search-type select of the picker (capture c2/02): its own text, Tên sản phẩm (the default) or Mã sản phẩm. */
export const SEARCH_BY_NAME = "Tên sản phẩm";
export const SEARCH_BY_ID = "Mã sản phẩm";

/** What the picker searches by now: "id" when its select shows Mã sản phẩm, "name" for Tên sản phẩm, null when not seen. */
export function searchMode(modal: HTMLElement): { mode: "id" | "name" | null; select: HTMLElement | null } {
  const selects = Array.from(modal.querySelectorAll<HTMLElement>(SELECT)).filter(
    (el) => usable(el) && !el.closest('[class*="options-list"],[class*="dropdown"]') && /(tên|mã) sản phẩm/.test(normalizeLabel(el.textContent ?? "")),
  );
  // the outermost select element (its inner parts carry the same class family)
  const select = selects.find((el) => !selects.some((o) => o !== el && o.contains(el))) ?? null;
  const text = normalizeLabel(select?.textContent ?? "");
  return { mode: text.includes(normalizeLabel(SEARCH_BY_ID)) ? "id" : text.includes(normalizeLabel(SEARCH_BY_NAME)) ? "name" : null, select };
}

/**
 * The step text of the product picker (F5.2; a2 C-E111): Shopee's picker searches by Tên sản phẩm
 * unless the person switches it, so a known product name is searched as is (the row ticked is the
 * one showing «Mã: <id>»); without a name the person switches the search to Mã sản phẩm first.
 */
export const pickStep = (opener: string, ids: readonly string[], names: Readonly<Record<string, string>> = {}) => {
  const named = ids.filter((id) => names[id]);
  if (named.length === ids.length) return `Bấm «${opener}», tìm ${ids.map((id) => `«${names[id]}»`).join(", ")}, tick dòng ${ids.map((id) => `Mã: ${id}`).join(", ")}, bấm Xác nhận của hộp chọn`;
  return `Bấm «${opener}», đổi ô tìm sang «${SEARCH_BY_ID}», tìm ${ids.join(", ")}, tick, bấm Xác nhận của hộp chọn`;
};

/**
 * 0.3.28: the product picker is the person's: "Thêm sản phẩm" is highlighted; once the person opens
 * the picker its search box gets the first id (a value write) and the rows of the card's ids are
 * highlighted. ✓ once the form (outside the picker) lists every id. Recorded under the env's key.
 */
export function pickProducts(env: Env, opener: string, ids: readonly string[], names: Readonly<Record<string, string>> = {}): PickResult {
  /** The form (outside the dialog) lists the product: its row shows the id. */
  const listed = (id: string) =>
    Array.from(env.doc.querySelectorAll<HTMLElement>("tr,li,[class*='row'],[role='row']")).some((r) => usable(r) && !r.closest('[role="dialog"],[class*="modal"]') && holdsId(r, id));
  const all = () => ids.every(listed);
  const key = env.log?.keyOf(env);
  const record = () => {
    if (env.log && key) env.log.wrote({ key, el: env.doc.body, want: `${ids.length} sản phẩm`, seen: () => `${ids.filter(listed).length} sản phẩm trong combo/voucher`, ok: all });
  };
  if (all()) {
    record();
    return { done: true };
  }
  const open = findPressable(env, opener);
  // no picker on this page at all: say so (the step keeps that note)
  if (!open && !pickerModal(env)) return { done: false, reason: PICK_NO_OPENER };
  record();
  if (open) highlight(open);
  if (env.log && key) {
    env.log.later({
      key: `${key}_search`,
      write: () => {
        const modal = pickerModal(env);
        const box = modal ? searchBox(modal) : undefined;
        if (!modal || !box) return false;
        const first = ids.find((id) => !listed(id)) ?? ids[0]!;
        // a2 C-E111: an id finds nothing while the picker searches by name (its default): the name
        // when Juli knows it, else the id with the search-type select shown for the person to switch
        const { mode, select } = searchMode(modal);
        const want = mode !== "id" && names[first] ? names[first]! : first;
        if (box.value !== want) writeValue(box, want);
        mark(box);
        if (want === first && mode !== "id" && select) highlight(select);
        for (const row of Array.from(modal.querySelectorAll<HTMLElement>("tr,li,[role='row']"))) {
          const check = row.querySelector<HTMLElement>(CHECKBOX);
          if (check && ids.some((id) => holdsId(row, id))) highlight(check);
        }
        return true;
      },
    });
  }
  return { done: false };
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
 * mới!" over the affiliate page): a dialog whose text matches one of these AND that holds no text
 * box (not a form). 0.3.28: the person closes it (its close icon or a button that only dismisses
 * is highlighted); the Connector never presses it.
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

export function noticeDialogs(env: Env): HTMLElement[] {
  const all = Array.from(env.doc.querySelectorAll<HTMLElement>('[role="dialog"],[class*="eds-modal"],[class*="modal"]')).filter(usable);
  const hits = all.filter((d) => {
    const text = normalizeLabel(d.textContent ?? "");
    return KNOWN_NOTICES.some((re) => re.test(text)) && !FEEDBACK_WIDGET.test(text) && textBoxesIn(d).length === 0;
  });
  // the outermost dialog of a notice (its close icon sits on the frame)
  return hits.filter((h) => !hits.some((o) => o !== h && o.contains(h)));
}

/** The title of a notice as the panel names it. */
export const noticeTitle = (dialog: Element) => (dialog.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 50);

/** The notice's own close (its close icon, else a button that only dismisses), or null. */
function noticeClose(env: Env, dialog: HTMLElement): HTMLElement | null {
  const icons = Array.from(dialog.querySelectorAll<HTMLElement>(CLOSE_ICON)).filter(usable);
  const icon = icons.find((i) => !icons.some((o) => o !== i && i.contains(o)));
  if (icon && unsafePress(icon) === null) return icon;
  for (const text of DISMISS_TEXTS) {
    const button = findPressable(env, text, dialog);
    if (button && unsafePress(button) === null) return button;
  }
  return null;
}

/** The step text of a notice the person closes (F5.2). */
export const noticeStep = (title: string) => `Đóng thông báo «${title}» của Shopee (dấu × hoặc «Để sau»)`;

/** Highlights the close of Shopee's known notices; the notes say which (for the panel). Presses nothing. */
export async function dismissNotices(env: Env): Promise<string[]> {
  const notes: string[] = [];
  for (const dialog of noticeDialogs(env)) {
    const close = noticeClose(env, dialog);
    if (close) highlight(close);
    notes.push(`Thông báo của Shopee «${noticeTitle(dialog)}» đang che trang; hãy tự đóng (Juli không bấm), Juli làm tiếp khi trang hiện ra.`);
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

/** The edit control (pencil) of a labelled card: aria-label / title "Chỉnh sửa", else its only pressable icon. Found, never pressed. */
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
