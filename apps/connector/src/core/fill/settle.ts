// Settle / write / verify one control, platform-free (0.3.20): a page may load its own value into
// a control AFTER the control appears and overwrite what was typed too early. The control is
// written only once its value has held still for FILL_STABLE_MS, read back FILL_RECHECK_MS later,
// and written again if the page put its own value back (at most FILL_MAX_REWRITES times).

import { FILL_MAX_REWRITES, FILL_POLL_MS, FILL_RECHECK_MS, FILL_STABLE_MS } from "../config";
import type { FillField } from "./types";
import { highlight, readValue, targetValue, writeValue } from "./write";

export interface SettleDeps {
  doc: Document;
  sleep(ms: number): Promise<void>;
  now(): number;
}

const valueOf = (control: HTMLElement) => readValue(control).replace(/\r/g, "");

/**
 * Wait until the page has loaded the product into the control: its value unchanged for
 * FILL_STABLE_MS and not empty (an existing product always has a title / description). Gives up
 * waiting at `until` (the FILL_WAIT_MS cap) and writes anyway.
 */
async function settled(deps: SettleDeps, control: HTMLElement, until: number): Promise<void> {
  let last = valueOf(control);
  let since = deps.now();
  for (;;) {
    const now = deps.now();
    if (now >= until) return;
    if (last.trim() !== "" && now - since >= FILL_STABLE_MS) return;
    await deps.sleep(FILL_POLL_MS);
    const value = valueOf(control);
    if (value !== last) {
      last = value;
      since = deps.now();
    }
  }
}

/**
 * Write the field the way a person typing would (native setter + input/change), then read it back
 * after FILL_RECHECK_MS and write it again if the page put its own value back (at most
 * FILL_MAX_REWRITES times). True only when the last read equals the target.
 */
export async function fillOne(deps: SettleDeps, control: HTMLElement, field: FillField, until: number): Promise<boolean> {
  await settled(deps, control, until);
  for (let attempt = 0; attempt <= FILL_MAX_REWRITES; attempt += 1) {
    if (!deps.doc.contains(control)) return false;
    const next = targetValue(valueOf(control), field.value, field.mode);
    if (valueOf(control) !== next && !writeValue(control, next)) return false;
    await deps.sleep(FILL_RECHECK_MS);
    if (!deps.doc.contains(control)) return false;
    if (valueOf(control) === next) {
      highlight(control);
      return true;
    }
  }
  return false;
}

