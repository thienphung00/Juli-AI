// Putting text into a control the way a person typing would, so the page's framework notices:
// the native value setter and a bubbling `input` + `change` event. Nothing else is dispatched
// (no click, key, pointer, focus-steal or submit events) and no form is ever submitted.

import type { FillMode } from "./types";

export function readValue(el: HTMLElement): string {
  if ("value" in el) return String((el as HTMLInputElement | HTMLTextAreaElement).value ?? "");
  return el.innerText ?? el.textContent ?? "";
}

/** The text the control should end up with: the whole value, or only its first line replaced. */
export function targetValue(current: string, value: string, mode: FillMode): string {
  if (mode === "replace") return value;
  const at = current.indexOf("\n");
  return at < 0 ? value : value + current.slice(at);
}

function nativeSet(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const win = el.ownerDocument.defaultView!;
  const proto = el instanceof win.HTMLTextAreaElement ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
}

function announce(el: HTMLElement, inputType: string, data: string): void {
  const win = el.ownerDocument.defaultView!;
  el.dispatchEvent(new win.InputEvent("input", { bubbles: true, inputType, data }));
  el.dispatchEvent(new win.Event("change", { bubbles: true }));
}

/** Sets the control's text; true when it reads back equal. Never throws on a hostile page. */
export function writeValue(el: HTMLElement, text: string): boolean {
  try {
    if ("value" in el) {
      nativeSet(el as HTMLInputElement | HTMLTextAreaElement, text);
      announce(el, "insertReplacementText", text);
    } else {
      // contenteditable: replace the text node content, then tell the editor.
      el.textContent = text;
      announce(el, "insertReplacementText", text);
    }
    return readValue(el).replace(/\r/g, "") === text;
  } catch {
    return false;
  }
}

export function highlight(el: HTMLElement): void {
  el.style.outline = "2px solid #db2777";
  el.style.outlineOffset = "2px";
  el.setAttribute("data-juli-filled", "1");
}
