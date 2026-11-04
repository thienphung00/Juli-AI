// The content script's fill flow. Trigger → ask the service worker for the card → find the
// controls by their visible labels → type the approved text → show the panel. It never clicks,
// submits or navigates; a page it does not recognise gets no fill, only the copy buttons.

import { FILL_CODE_PATTERN, FILL_EDIT_PATH, FILL_HASH_KEY, FILL_LABELS, FILL_POLL_MS, FILL_WAIT_MS } from "../config";
import { findControl } from "./locate";
import { type PanelDeps, type PanelInput, showPanel } from "./panel";
import type { FillField, FillKey, FillReply, FillRequest } from "./types";
import { highlight, readValue, targetValue, writeValue } from "./write";

export interface Trigger {
  itemId: string;
  code: string;
}

/** `/portal/product/<id>` with `#juli-fill=<card code>`; anything else is not ours. */
export function parseTrigger(loc: { pathname: string; hash: string }): Trigger | null {
  const path = FILL_EDIT_PATH.exec(loc.pathname);
  if (!path) return null;
  const hash = loc.hash.replace(/^#/, "");
  const prefix = `${FILL_HASH_KEY}=`;
  if (!hash.startsWith(prefix)) return null;
  const code = hash.slice(prefix.length);
  if (!FILL_CODE_PATTERN.test(code)) return null;
  return { itemId: path[1] as string, code };
}

export interface RunDeps {
  doc: Document;
  loc: { pathname: string; hash: string };
  /** Asks the service worker (flag, pilot shop and Juli decide there). */
  ask(trigger: Trigger): Promise<FillReply>;
  panel: PanelDeps;
  sleep(ms: number): Promise<void>;
  now(): number;
}

export type RunResult =
  | { status: "idle" }
  | { status: "refused"; reason: string }
  | { status: "filled"; keys: FillKey[] }
  | { status: "not_found" }
  | { status: "page_only" };

async function locate(deps: RunDeps, fields: readonly FillField[]): Promise<Map<FillKey, HTMLElement>> {
  const found = new Map<FillKey, HTMLElement>();
  const until = deps.now() + FILL_WAIT_MS;
  for (;;) {
    for (const f of fields) {
      if (found.has(f.key)) continue;
      const control = findControl(deps.doc, FILL_LABELS[f.key]);
      if (control) found.set(f.key, control);
    }
    if (found.size === fields.length || deps.now() >= until) return found;
    await deps.sleep(FILL_POLL_MS);
  }
}

function fillOne(control: HTMLElement, field: FillField): boolean {
  const current = readValue(control).replace(/\r/g, "");
  const next = targetValue(current, field.value, field.mode);
  if (current === next || writeValue(control, next)) {
    highlight(control);
    return true;
  }
  return false;
}

export async function runFill(deps: RunDeps): Promise<RunResult> {
  const trigger = parseTrigger(deps.loc);
  if (!trigger) return { status: "idle" };
  const reply = await deps.ask(trigger);
  if (!reply.ok) {
    if (reply.reason === "inactive") return { status: "idle" };
    showPanel(deps.doc, { outcome: "refused", refusal: reply.reason }, deps.panel);
    return { status: "refused", reason: reply.reason };
  }
  const request: FillRequest = reply.value;
  if (request.itemId !== trigger.itemId || request.code !== trigger.code) {
    showPanel(deps.doc, { outcome: "refused", refusal: "wrong_item" }, deps.panel);
    return { status: "refused", reason: "wrong_item" };
  }
  if (request.fields.length === 0) {
    showPanel(deps.doc, { outcome: "page_only", request }, deps.panel);
    return { status: "page_only" };
  }
  const controls = await locate(deps, request.fields);
  const filled: FillKey[] = [];
  for (const f of request.fields) {
    const control = controls.get(f.key);
    if (control && deps.doc.contains(control) && fillOne(control, f)) filled.push(f.key);
  }
  const input: PanelInput =
    filled.length === request.fields.length
      ? { outcome: "filled", request, filled }
      : { outcome: "not_found", request, filled };
  showPanel(deps.doc, input, deps.panel);
  return filled.length === request.fields.length ? { status: "filled", keys: filled } : { status: "not_found" };
}
