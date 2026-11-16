// The controls a TikTok create form needs: text / number boxes, radios, checkboxes, a native
// select. Seller Center follows the browser language (EN or VI), so a control is found by the
// visible label next to it OR its ARIA name, matched against the English and the Vietnamese
// wording; the structure (a label's nearest ancestor holding a control) decides, never a class
// name. Anything unclear (no row, a label twice, no such option) returns false and touches nothing.
//
// The only thing this file ever clicks is a radio / checkbox, and `press()` refuses anything that
// publishes, saves, confirms or cancels (TikTok's "Agree and publish" / "Đồng ý và đăng" included).

import type { Env } from "../../core/fill/form";
import { normalizeLabel, PANEL_ID } from "../../core/fill/locate";
import { writeValue } from "../../core/fill/write";

export type { Env };
/** One field's labels: the English and Vietnamese wordings. */
export type Labels = readonly string[];

const norm = (raw: string) => normalizeLabel(raw.replace(/\(\s*gmt\s*[+-]\s*\d+\s*\)/gi, " "));
const wantedSet = (labels: Labels) => new Set(labels.map(norm));

/** Texts that publish, save, confirm, cancel or delete: never pressed. */
export const FORBIDDEN_PRESS =
  /^(agree and publish|agree & publish|publish|submit|save|confirm|create|cancel|delete|done|ok|đồng ý và đăng|đồng ý|đăng|gửi|lưu|xác nhận|tạo|hủy|huỷ|xóa|xoá|hoàn tất)$/;

function hidden(el: Element): boolean {
  if (el.closest("[hidden],[aria-hidden='true']")) return true;
  const view = el.ownerDocument.defaultView;
  for (let node: Element | null = el; node; node = node.parentElement) {
    const style = view?.getComputedStyle(node);
    if (style && (style.display === "none" || style.visibility === "hidden")) return true;
  }
  return false;
}
const usable = (el: Element) => !el.closest(`#${PANEL_ID}`) && !hidden(el);

function ownText(el: Element): string {
  let out = "";
  for (const n of Array.from(el.childNodes)) if (n.nodeType === 3) out += n.nodeValue ?? "";
  return out;
}

/** Why a press was refused: the text or type that made it unsafe; null when it is safe. */
export function unsafePress(el: Element): string | null {
  const text = norm((el.textContent ?? "").slice(0, 80));
  if (FORBIDDEN_PRESS.test(text) || /agree and publish|đồng ý và đăng/.test(text)) return text;
  const submits = (b: Element) => (b.tagName === "BUTTON" || b.tagName === "INPUT") && (b.getAttribute("type") ?? "").toLowerCase() === "submit";
  if (submits(el)) return "type=submit";
  const button = el.closest("button");
  if (button && button !== el) {
    const inner = norm((button.textContent ?? "").slice(0, 80));
    if (FORBIDDEN_PRESS.test(inner)) return inner;
    if (submits(button)) return "type=submit";
  }
  return null;
}

/** The single place the fill code clicks something. Returns false (and clicks nothing) when unsafe. */
export function press(el: HTMLElement): boolean {
  if (unsafePress(el) !== null) return false;
  el.click();
  return true;
}

const CONTROLISH = 'input,textarea,select,[role="radio"],[role="checkbox"],[role="combobox"],[role="spinbutton"]';

/** The labelled row: the nearest ancestor of a matching label (visible text or ARIA name) holding a control. Null if none or two. */
export function findRow(doc: Document, labels: Labels, within?: Element): HTMLElement | null {
  const wanted = wantedSet(labels);
  const root: ParentNode = within ?? doc.body;
  if (!root) return null;
  const rows = new Set<HTMLElement>();
  for (const el of Array.from(root.querySelectorAll("*"))) {
    if (el.tagName === "SCRIPT" || el.tagName === "STYLE" || !usable(el)) continue;
    const aria = el.getAttribute("aria-label");
    if (aria !== null && wanted.has(norm(aria)) && el.matches(CONTROLISH)) {
      rows.add(el as HTMLElement);
      continue;
    }
    if (!wanted.has(norm(ownText(el)))) continue;
    for (let scope: Element | null = el, depth = 0; scope && depth < 6; scope = scope.parentElement, depth += 1) {
      if (scope !== el && Array.from(scope.querySelectorAll(CONTROLISH)).some(usable)) {
        rows.add(scope as HTMLElement);
        break;
      }
    }
  }
  return rows.size === 1 ? ([...rows][0] as HTMLElement) : null;
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

export function mark(el: HTMLElement): true {
  el.style.outline = "2px solid #db2777";
  el.style.outlineOffset = "2px";
  el.setAttribute("data-juli-filled", "1");
  return true;
}

/** The row's editable text / number boxes (the row itself when it is one). */
export function textBoxesIn(row: Element): HTMLInputElement[] {
  const sel = 'input:not([type]),input[type="text"],input[type="number"],input[type="tel"]';
  const all = row.matches(sel) ? [row as HTMLInputElement] : Array.from(row.querySelectorAll<HTMLInputElement>(sel));
  return all.filter((i) => usable(i) && !i.disabled && !i.readOnly);
}

/** Types into the `index`-th box of the labelled row; true when it reads back equal. */
export function setRowText(env: Env, labels: Labels, value: string, index = 0): boolean {
  const row = findRow(env.doc, labels);
  const box = row ? textBoxesIn(row)[index] : undefined;
  return !!box && writeValue(box, value) && box.value === value && mark(box);
}

/** Types a GMT+7 `YYYY-MM-DD HH:mm` into the labelled row's date box and time box. */
export function setDateTime(env: Env, labels: Labels, value: string): boolean {
  const row = findRow(env.doc, labels);
  const boxes = row ? textBoxesIn(row) : [];
  const [date, time] = [boxes[0], boxes[1]];
  if (!date || !time) return false;
  const d = value.slice(0, 10);
  const t = value.slice(11, 16);
  return writeValue(date, d) && date.value === d && writeValue(time, t) && time.value === t && mark(date) && mark(time);
}

// -- radios and checkboxes ---------------------------------------------------------------------

const OPTION = 'input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]';

function optionText(el: Element): string {
  const aria = el.getAttribute("aria-label");
  if (aria) return aria;
  const label = el.closest("label");
  if (label) return label.textContent ?? "";
  const own = (el.textContent ?? "").trim();
  if (own) return own;
  return el.parentElement?.textContent ?? "";
}

function isOn(el: Element): boolean {
  if (el.matches("input")) return (el as HTMLInputElement).checked;
  return el.getAttribute("aria-checked") === "true";
}

function optionIn(row: Element, labels: Labels): HTMLElement | null {
  const wanted = wantedSet(labels);
  const hits = Array.from(row.querySelectorAll<HTMLElement>(OPTION)).filter((o) => usable(o) && wanted.has(norm(optionText(o))));
  return hits.length === 1 ? (hits[0] as HTMLElement) : null;
}

/** Makes the radio (or checkbox) `option` of the labelled group be `on`; verifies it reads back. */
export async function setOption(env: Env, group: Labels, option: Labels, on = true, within?: Element): Promise<boolean> {
  const row = within ?? findRow(env.doc, group);
  if (!row) return false;
  const target = optionIn(row, option);
  if (!target) return false;
  if (isOn(target) !== on) {
    const holder = (target.matches("input") ? target.closest("label") : null) ?? target;
    if (!press(holder as HTMLElement)) return false;
  }
  const settled = await waitFor(env, () => (isOn(target) === on ? true : null), 1_000);
  return !!settled && mark(target);
}

// -- select ------------------------------------------------------------------------------------

/** Picks the option of a NATIVE select in the labelled row (a custom drop-down is left to the seller). */
export function setSelect(env: Env, labels: Labels, optionText: Labels): boolean {
  const row = findRow(env.doc, labels);
  const select = row ? (row.matches("select") ? (row as HTMLSelectElement) : row.querySelector<HTMLSelectElement>("select")) : null;
  if (!select || !usable(select)) return false;
  const wanted = wantedSet(optionText);
  const hit = Array.from(select.options).find((o) => wanted.has(norm(o.text)) || wanted.has(norm(o.value)));
  if (!hit) return false;
  const win = env.doc.defaultView!;
  const setter = Object.getOwnPropertyDescriptor(win.HTMLSelectElement.prototype, "value")?.set;
  if (setter) setter.call(select, hit.value);
  else select.value = hit.value;
  select.dispatchEvent(new win.Event("input", { bubbles: true }));
  select.dispatchEvent(new win.Event("change", { bubbles: true }));
  return select.value === hit.value && mark(select);
}

/** A language-free fallback for a name box: the page's one text box with `maxlength="50"`. */
export function nameBox(doc: Document): HTMLInputElement | null {
  const boxes = Array.from(doc.querySelectorAll<HTMLInputElement>('input[maxlength="50"]')).filter((i) => usable(i) && !i.disabled && !i.readOnly);
  return boxes.length === 1 ? (boxes[0] as HTMLInputElement) : null;
}

export { waitFor };
