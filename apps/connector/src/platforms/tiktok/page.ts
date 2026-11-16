// What the TikTok Seller Center page itself says: which shop it is signed in to, and whether a
// verification (CAPTCHA) is in the way. Pure DOM reads.

import { PANEL_ID } from "../../core/fill/locate";

const CLEAN = (s: string) => s.replace(/\s+/g, " ").trim();

function hidden(el: Element): boolean {
  if (el.closest("[hidden],[aria-hidden='true']")) return true;
  const view = el.ownerDocument.defaultView;
  for (let node: Element | null = el; node; node = node.parentElement) {
    const style = view?.getComputedStyle(node);
    if (style && (style.display === "none" || style.visibility === "hidden")) return true;
  }
  return false;
}

/** The Seller Center page header (banner) nodes: where the signed-in shop's name is drawn. */
const HEADER = 'header,[role="banner"],[class*="header" i],[class*="topbar" i],[class*="navbar" i]';
/** An element that names the shop / account (explicit hooks first, then class names). */
const NAME_HOOK = '[data-shop-name],[data-testid*="shop-name" i],[class*="shop-name" i],[class*="shopname" i],[class*="seller-name" i],[class*="account-name" i],[class*="store-name" i]';

/**
 * The shop the page is signed in to: the name drawn in the page header (e.g. "SANDBOX_VN…"; a long
 * name may be shown cut with an ellipsis). TikTok's create pages carry no stable shop id in the
 * DOM, so this is the visible name; the caller compares it with the name Juli holds for the paired
 * shop (`sameShop`). Null when the header does not show one.
 */
export function shopOnPage(doc: Document): string | null {
  const body = doc.body;
  if (!body) return null;
  const hooks = Array.from(body.querySelectorAll(NAME_HOOK)).filter((el) => !el.closest(`#${PANEL_ID}`) && !hidden(el));
  const inHeader = hooks.filter((el) => el.closest(HEADER));
  const pool = inHeader.length > 0 ? inHeader : hooks;
  const names = new Set<string>();
  for (const el of pool) {
    const own = el.getAttribute("data-shop-name") ?? CLEAN(el.textContent ?? "");
    if (own.length >= 2 && own.length <= 80) names.add(own);
  }
  return names.size === 1 ? ([...names][0] as string) : null;
}

const fold = (s: string) => CLEAN(s.normalize("NFC")).toLowerCase();

/** The two names are the same shop (case and spacing aside; a name cut with "…" / "..." matches its start). */
export function sameShop(onPage: string, expected: string): boolean {
  const a = fold(onPage);
  const b = fold(expected);
  if (a === b) return true;
  const cut = (s: string) => (/(…|\.\.\.)$/.test(s) ? s.replace(/(…|\.\.\.)$/, "").trimEnd() : null);
  const ac = cut(a);
  const bc = cut(b);
  return (ac !== null && ac.length >= 4 && b.startsWith(ac)) || (bc !== null && bc.length >= 4 && a.startsWith(bc));
}

const CAPTCHA_NODE = '[id*="captcha" i],[class*="captcha" i],iframe[src*="captcha" i],[class*="secsdk" i],[class*="verify-bar" i]';
const CAPTCHA_TEXT = /(drag the puzzle|drag the slider|verify to continue|security verification|kéo mảnh ghép|kéo thanh trượt|xác minh bảo mật|xác minh để tiếp tục)/i;

/** A CAPTCHA / verification puzzle is showing on the page (EN or VI). */
export function captchaVisible(doc: Document): boolean {
  const body = doc.body;
  if (!body) return false;
  if (Array.from(body.querySelectorAll(CAPTCHA_NODE)).some((el) => !el.closest(`#${PANEL_ID}`) && !hidden(el))) return true;
  const text = Array.from(body.querySelectorAll('[role="dialog"],[class*="modal" i],[class*="mask" i]'))
    .filter((el) => !el.closest(`#${PANEL_ID}`) && !hidden(el))
    .map((el) => el.textContent ?? "")
    .join(" ");
  return CAPTCHA_TEXT.test(text);
}

/** The core's wall hook for this pack. */
export function blockedOn(doc: Document): string | null {
  return captchaVisible(doc) ? "blocked_captcha" : null;
}
