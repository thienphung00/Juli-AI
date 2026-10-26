/**
 * Short product names for headings and queue rows (owner: no full TikTok titles).
 * Strips parentheticals, cuts at the first clause break or ~40 characters on a word
 * boundary, adds "…". The full name goes in the `title` attribute. Mirrors the backend
 * `services/product_name.py`; keep the two in step.
 */

export const MAX_NAME_CHARS = 40;
const MIN_CLAUSE_CHARS = 12;

const PARENTHETICAL = /\s*[(\[（][^)\]）]*[)\]）]/g;
const CLAUSE_BREAK = /\s*[,;|–—]\s+|\s+-\s+/;
const TRAILING_JUNK = /[\s,;:|\-–—/·]+$/;

export function shortProductName(name: string | null | undefined, maxChars = MAX_NAME_CHARS): string {
  let text = (name ?? "").replace(PARENTHETICAL, "").split(/\s+/).filter(Boolean).join(" ");
  if (!text) return "";
  let cut = false;
  const clause = CLAUSE_BREAK.exec(text);
  if (clause && clause.index >= MIN_CLAUSE_CHARS) {
    text = text.slice(0, clause.index);
    cut = true;
  }
  if (text.length > maxChars) {
    const head = text.slice(0, maxChars + 1);
    const space = head.lastIndexOf(" ");
    text = space >= MIN_CLAUSE_CHARS ? head.slice(0, space) : text.slice(0, maxChars);
    cut = true;
  }
  text = text.replace(TRAILING_JUNK, "");
  return cut ? `${text}…` : text;
}
