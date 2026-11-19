// 0.3.24: the record of one form fill. Before a control is written its current value is kept
// (`before`, what a revert puts back); after it is written the write is kept as an entry the
// runner reads again later (a page may put its own value back, or never take the write). A step
// is ✓ only when every entry it stands for still reads what the card holds.

import type { Env } from "./form";

/** Bounded so a report never carries a whole description. */
export const MAX_BEFORE_CHARS = 600;
export const FIELD_KEY = /^[a-z][a-z0-9_]{0,39}$/;

export interface Entry {
  key: string;
  el: HTMLElement;
  /** What the card holds, as the control shows it (for the panel). */
  want: string;
  /** What the control shows now. */
  seen(): string;
  /** The control holds the card's value. */
  ok(): boolean;
  /** Writes the value again (text boxes only; a press is never repeated). */
  rewrite?(): boolean;
}

/**
 * 0.3.28 (F5.2): a text box the person's click will reveal (a tier row, the rate editor, a picker's
 * search box). `write` is tried on each re-check; it returns true once it wrote (it is then dropped),
 * false while the box is not there yet. It only ever writes a value (never a click).
 */
export interface Later {
  key: string;
  write(): boolean;
}

export interface FieldCheck {
  key: string;
  ok: boolean;
  seen: string;
}

export class FillLog {
  readonly before: Record<string, string> = {};
  readonly entries = new Map<string, Entry>();
  private n = 0;

  /** The key a write is filed under: the env's field key, else a generated one. */
  keyOf(env: Env): string {
    if (env.field && FIELD_KEY.test(env.field)) return env.field;
    this.n += 1;
    return `field_${this.n}`;
  }

  /** The value before the first write of `key` (a later write of the same key keeps the first). */
  captureBefore(key: string, value: string): void {
    if (!Object.prototype.hasOwnProperty.call(this.before, key)) this.before[key] = value.slice(0, MAX_BEFORE_CHARS);
  }

  wrote(entry: Entry): void {
    this.entries.set(entry.key, entry);
  }

  /** The boxes still waiting for the person's click to reveal them. */
  readonly pending = new Map<string, Later>();

  later(l: Later): void {
    this.pending.set(l.key, l);
  }

  /** Writes every revealed box once; true when one was written. A failing write is tried again later. */
  revealed(): boolean {
    let any = false;
    for (const [key, l] of [...this.pending]) {
      let done = false;
      try {
        done = l.write();
      } catch {
        done = false;
      }
      if (done) {
        this.pending.delete(key);
        any = true;
      }
    }
    return any;
  }
}

/** The env whose next writes belong to field `key`. */
export function keyed(env: Env, key: string): Env {
  return { ...env, field: key };
}
