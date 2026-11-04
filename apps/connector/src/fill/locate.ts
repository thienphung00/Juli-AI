// Finding a form control by the visible label next to it. Pure DOM reads: no layout, no clicks,
// no network. Anything unclear (no label, a label used twice, two inputs under one label) returns
// null and the caller fills nothing.

const CONTROL = [
  'input:not([type])',
  'input[type="text"]',
  "textarea",
  '[contenteditable=""]',
  '[contenteditable="true"]',
].join(",");

/** The panel's own nodes and anything the page hides are never candidates. */
export const PANEL_ID = "juli-fill-root";

export function normalizeLabel(raw: string): string {
  return raw
    .normalize("NFC")
    .replace(/ /g, " ")
    .replace(/\d+\s*\/\s*\d+/g, " ")
    .replace(/[*:]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("vi");
}

function ownText(el: Element): string {
  let out = "";
  for (const node of Array.from(el.childNodes)) {
    if (node.nodeType === 3) out += node.nodeValue ?? "";
  }
  return out;
}

function inPanel(el: Element): boolean {
  return !!el.closest(`#${PANEL_ID}`);
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

function editable(el: Element): boolean {
  if (el instanceof el.ownerDocument.defaultView!.HTMLInputElement || el instanceof el.ownerDocument.defaultView!.HTMLTextAreaElement) {
    return !el.disabled && !el.readOnly;
  }
  return true;
}

function usable(el: Element): boolean {
  return !inPanel(el) && editable(el) && !hidden(el);
}

function controlsIn(scope: Element): Element[] {
  return Array.from(scope.querySelectorAll(CONTROL)).filter(usable);
}

/** The one control a label element belongs to, or null. */
function controlOf(labelEl: Element): Element | null {
  if (labelEl.tagName === "LABEL") {
    const id = (labelEl as HTMLLabelElement).htmlFor;
    if (id) {
      const target = labelEl.ownerDocument.getElementById(id);
      if (target && target.matches(CONTROL) && usable(target)) return target;
    }
  }
  // The nearest ancestor that holds any control: it must hold exactly one.
  let scope: Element | null = labelEl;
  for (let depth = 0; depth < 6 && scope; depth += 1) {
    const found = controlsIn(scope);
    if (found.length === 1) return found[0] ?? null;
    if (found.length > 1) return null;
    scope = scope.parentElement;
  }
  return null;
}

/** The control whose visible label is `label`; null when there is none or more than one. */
export function findControl(doc: Document, label: string): HTMLElement | null {
  const wanted = normalizeLabel(label);
  const body = doc.body;
  if (!body) return null;
  const labels = Array.from(body.querySelectorAll("*")).filter((el) => {
    if (el.tagName === "SCRIPT" || el.tagName === "STYLE" || inPanel(el)) return false;
    return normalizeLabel(ownText(el)) === wanted && !hidden(el);
  });
  const controls = new Set<Element>();
  for (const el of labels) {
    const control = controlOf(el);
    if (control) controls.add(control);
  }
  if (controls.size !== 1) return null;
  return [...controls][0] as HTMLElement;
}
