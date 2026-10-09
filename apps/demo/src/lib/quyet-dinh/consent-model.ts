/**
 * The consent option's before → after rows (`Run.dc.html`, `Revert.dc.html`,
 * `RunPhoto.dc.html`) — pure. The proposed value comes from the
 * `workflow.approval_required` option; the "before" from a `{from, to}`
 * value when the payload carries one, else the card's `before_after`
 * (contract §1), else — for the title only — the run's product name. Never
 * invented: a field with no known before shows the proposed value alone.
 */

import type { CardView } from "./card-model";
import { FIELD_LABELS } from "./copy";
import { summariseText } from "./p10-format";

export interface ConsentRow {
  readonly field: string;
  readonly label: string;
  readonly before: string | null;
  readonly after: string;
  readonly strikeBefore: boolean;
  readonly strongAfter: boolean;
}

function asText(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return null;
}

function fromTo(value: unknown): { from: string | null; to: string | null } | null {
  if (value && typeof value === "object" && !Array.isArray(value) && "to" in value) {
    const v = value as { from?: unknown; to?: unknown };
    return { from: asText(v.from), to: asText(v.to) };
  }
  return null;
}

/** The text value Juli proposes for a field (a plain value, or `to`). */
export function proposedText(value: unknown): string | null {
  return fromTo(value)?.to ?? asText(value);
}

export function consentRows(
  change: Record<string, unknown>,
  context: { readonly revert: boolean; readonly productName: string; readonly card: CardView | null },
): ConsentRow[] {
  const rows: ConsentRow[] = [];
  for (const [field, value] of Object.entries(change)) {
    const pair = fromTo(value);
    const after = pair?.to ?? asText(value);
    if (after === null) continue;
    const known = context.card?.beforeAfter.find((row) => row.field === field) ?? null;
    const label = known?.label ?? FIELD_LABELS[field] ?? "Thay đổi được đề xuất";
    const long = field === "description" || after.length > 80;
    let before: string | null = pair?.from ?? null;
    if (before === null && known) before = context.revert ? known.after : known.before;
    if (before === null && field === "title" && !context.revert) before = context.productName;
    if (context.revert) {
      rows.push({
        field,
        label,
        before: before === null ? null : long ? summariseText(before, "after") : before,
        after: long ? summariseText(after, "before") : after,
        strikeBefore: true,
        strongAfter: true,
      });
    } else {
      rows.push({
        field,
        label,
        before: before === null ? null : long ? summariseText(before, "before") : before,
        after: long ? summariseText(after, "after") : after,
        strikeBefore: !long,
        strongAfter: !long,
      });
    }
  }
  return rows;
}

/** Image URLs in an upload proposal: `{from, to}` or the first URL-looking string. */
export function photoUrls(change: Record<string, unknown>): { before: string | null; after: string | null } {
  const looksLikeUrl = (s: string | null) => (s && /^(https?:|\/|data:image)/.test(s) ? s : null);
  for (const value of Object.values(change)) {
    const pair = fromTo(value);
    if (pair) return { before: looksLikeUrl(pair.from), after: looksLikeUrl(pair.to) };
  }
  for (const value of Object.values(change)) {
    const url = looksLikeUrl(asText(value));
    if (url) return { before: null, after: url };
    if (Array.isArray(value) && typeof value[0] === "string") return { before: null, after: looksLikeUrl(value[0]) };
  }
  return { before: null, after: null };
}

/** Which fields the seller may edit before consent (contract §3). */
export function editableFields(change: Record<string, unknown>): ("title" | "description")[] {
  return (["title", "description"] as const).filter((field) => proposedText(change[field]) !== null);
}
