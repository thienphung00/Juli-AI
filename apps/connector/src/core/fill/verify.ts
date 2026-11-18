// 0.3.24, platform-free: wait for the page's form, then re-read every write before a step may say ✓.
//
// Live runs (2026-11-17) showed a fill reporting ✓ while the page still held its own value (the
// write landed before the page loaded its data), and a form filled at once on a page that had not
// drawn it yet (0 of 10 fields). So: wait until the form is drawn and the page has stopped
// changing; after the form is typed, read every field again (write a text box again if the page
// put its own value back), and a step is ✓ only when what the control shows equals the card.

import { FILL_CONFIRM_MS, FILL_MAX_REWRITES, FILL_POLL_MS, FILL_QUIET_MS, FILL_RECHECK_MS, FILL_WAIT_MS } from "../config";
import type { Env, FillOutcome, Step } from "./form";
import { PANEL_ID } from "./locate";
import type { FieldCheck, FillLog } from "./log";

const SEEN_CHARS = 60;

/**
 * Waits (at most FILL_WAIT_MS) until `probe` holds, calling `clear` on every turn (it may close a
 * known notice that covers the page), then until the page has had no DOM change for FILL_QUIET_MS.
 * Returns the notes `clear` produced and whether the form was seen.
 */
export async function waitForForm(
  env: Env,
  probe: (() => boolean) | undefined,
  clear?: (env: Env) => Promise<string[]>,
): Promise<{ ready: boolean; notes: string[] }> {
  const notes: string[] = [];
  const until = env.now() + FILL_WAIT_MS;
  let last = env.now();
  const win = env.doc.defaultView;
  const observer =
    win && typeof win.MutationObserver === "function"
      ? new win.MutationObserver((records) => {
          if (records.some((r) => !(r.target instanceof win.Node) || !inPanel(r.target as Node))) last = env.now();
        })
      : null;
  observer?.observe(env.doc.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
  // a clock that does not move (a test double) must not spin: the turns are bounded too
  const turns = Math.ceil(FILL_WAIT_MS / FILL_POLL_MS);
  try {
    let ready = false;
    for (let turn = 0; ; turn += 1) {
      if (clear) notes.push(...(await clear(env)));
      ready = !probe || probe();
      if (ready || env.now() >= until || turn >= turns) break;
      await env.sleep(FILL_POLL_MS);
    }
    if (!ready) return { ready, notes };
    last = Math.max(last, env.now() - FILL_QUIET_MS + FILL_POLL_MS);
    for (let turn = 0; env.now() - last < FILL_QUIET_MS && env.now() < until && turn < turns; turn += 1) await env.sleep(FILL_POLL_MS);
    return { ready, notes };
  } finally {
    observer?.disconnect();
  }
}

function inPanel(node: Node): boolean {
  const el = node.nodeType === 1 ? (node as Element) : node.parentElement;
  return !!el?.closest(`#${PANEL_ID}`) || (el as Element | null)?.id === PANEL_ID;
}

function check(env: Env, log: FillLog): FieldCheck[] {
  return [...log.entries.values()].map((e) => {
    const there = env.doc.contains(e.el);
    let ok = false;
    let seen = "";
    try {
      ok = there && e.ok();
      seen = there ? e.seen() : "";
    } catch {
      ok = false;
    }
    return { key: e.key, ok, seen: seen.slice(0, 120) };
  });
}

/**
 * Reads every write again FILL_RECHECK_MS later; a text box the page changed back is written
 * again (at most FILL_MAX_REWRITES times); then one last read FILL_CONFIRM_MS later decides.
 */
export async function verifyWrites(env: Env, log: FillLog): Promise<FieldCheck[]> {
  if (log.entries.size === 0) return [];
  for (let attempt = 0; attempt <= FILL_MAX_REWRITES; attempt += 1) {
    await env.sleep(FILL_RECHECK_MS);
    const bad = check(env, log).filter((c) => !c.ok);
    if (bad.length === 0) break;
    let rewrote = false;
    for (const c of bad) {
      const e = log.entries.get(c.key);
      if (e?.rewrite && env.doc.contains(e.el)) {
        try {
          rewrote = e.rewrite() || rewrote;
        } catch {
          // a hostile page: the last read decides
        }
      }
    }
    if (!rewrote) break;
  }
  await env.sleep(FILL_CONFIRM_MS);
  return check(env, log);
}

/** What the panel says when a control does not hold the card's value. */
export function seenNote(seen: string): string {
  const s = seen.replace(/\s+/g, " ").trim();
  if (!s) return "Ô trên trang đang trống — Juli chưa điền được";
  return `Trang đang hiện «${s.length > SEEN_CHARS ? `${s.slice(0, SEEN_CHARS)}…` : s}»`;
}

/** The outcome with every step whose writes do not read back turned ✗ (with what the page shows). */
export function applyChecks(outcome: FillOutcome, checks: readonly FieldCheck[]): FillOutcome {
  const byKey = new Map(checks.map((c) => [c.key, c]));
  const steps = outcome.steps.map((s): Step => {
    if (!s.keys || s.keys.length === 0) return s;
    const bad = s.keys.map((k) => byKey.get(k)).find((c) => c !== undefined && !c.ok);
    if (!bad) return s;
    // a write that does not read back: say what the page shows (also on a step already ✗)
    return { ...s, ok: false, note: seenNote(bad.seen) };
  });
  return { ...outcome, steps };
}

/** False when the form has period fields and any of them does not hold the card's dates. */
export function periodOk(outcome: FillOutcome): boolean | undefined {
  const keys = outcome.periodKeys;
  if (!keys || keys.length === 0) return undefined;
  const steps = outcome.steps.filter((s) => s.keys?.some((k) => keys.includes(k)));
  return steps.length > 0 && steps.every((s) => s.ok);
}
