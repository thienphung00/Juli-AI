// The order list page's DOM, read by the page hook for the orders reader (Connector 0.3.20).
//
// Seller Centre's list page (/portal/sale/order) loads its orders through Shopee's DRM bundle, so
// no list answer reaches the hook. What the page still shows (captured 2026-11-15): every order
// card links to `/portal/sale/order/<order_id>` and shows "Mã đơn hàng <order_sn>". Only those two
// ids are read; no buyer name, address or anything else on the card. The pager's "next" control is
// the page's own navigation (a read): it is the only element the reader ever activates, and only
// when it is enabled and inside a pager.
//
// TODO(live check): the pager selector below is a best guess at Shopee's design system
// (eds-pager); confirm on the real list page.

import type { OrderLink } from "./reader";

const ORDER_HREF = /\/portal\/sale\/order\/(\d{6,25})(?:[/?#]|$)/;
const ORDER_SN = /Mã đơn hàng\s*:?\s*([0-9A-Z]{8,25})/i;

function idOfLink(anchor: Element): string | undefined {
  return ORDER_HREF.exec(anchor.getAttribute("href") ?? "")?.[1];
}

/** The order number shown on the card that holds `anchor` (the nearest ancestor with one order). */
function snNear(anchor: Element, id: string): string | undefined {
  let node: Element | null = anchor;
  for (let depth = 0; depth < 10 && node; depth += 1, node = node.parentElement) {
    const ids = new Set(
      Array.from(node.querySelectorAll('a[href*="/portal/sale/order/"]'))
        .map(idOfLink)
        .filter((x): x is string => x !== undefined),
    );
    if (anchor !== node && (ids.size > 1 || (ids.size === 1 && !ids.has(id)))) return undefined; // climbed past the card
    const match = ORDER_SN.exec(node.textContent ?? "");
    if (match) return match[1]?.toUpperCase();
  }
  return undefined;
}

/** The orders the list page shows now, in page order (each once). */
export function orderLinksIn(doc: Document): OrderLink[] {
  const out = new Map<string, OrderLink>();
  for (const anchor of Array.from(doc.querySelectorAll('a[href*="/portal/sale/order/"]'))) {
    const id = idOfLink(anchor);
    if (!id) continue;
    const known = out.get(id);
    if (known?.sn) continue;
    const sn = snNear(anchor, id);
    out.set(id, { id, ...(sn ? { sn } : {}) });
  }
  return [...out.values()];
}

/** The list page shows its "no orders" state and no order card. */
export function orderListEmptyIn(doc: Document): boolean {
  if (orderLinksIn(doc).length > 0) return false;
  return /Không (tìm thấy|có) đơn hàng/i.test(doc.body?.textContent ?? "");
}

const PAGER_NEXT = [
  ".eds-pager__button-next",
  ".shopee-pager__button-next",
  ".ant-pagination-next",
  "[class*='pager'] [class*='next']",
  "[class*='pagination'] [class*='next']",
  "[class*='pager'] [aria-label*='next' i]",
  "[class*='pagination'] [aria-label*='next' i]",
];

function disabled(el: Element): boolean {
  if ((el as HTMLButtonElement).disabled) return true;
  if (el.getAttribute("aria-disabled") === "true") return true;
  return /disabled/i.test(el.getAttribute("class") ?? "") || !!el.closest("[class*='disabled' i][class*='next' i]");
}

/** The pager's enabled "next" control: exactly one candidate inside a pager, else null. */
export function pagerNextIn(doc: Document): HTMLElement | null {
  for (const selector of PAGER_NEXT) {
    const found = Array.from(doc.querySelectorAll(selector)).filter((el) => el.parentElement?.closest("[class*='pager' i], [class*='pagination' i]"));
    // A nested match (the button and its icon) counts once: keep the outermost.
    const outer = found.filter((el) => !found.some((other) => other !== el && other.contains(el)));
    if (outer.length === 0) continue;
    if (outer.length > 1) return null;
    const next = outer[0] as HTMLElement;
    return disabled(next) ? null : next;
  }
  return null;
}

/** Go to the next list page with the page's own pager; false when there is no enabled one. */
export function goToNextOrderPage(doc: Document): boolean {
  const next = pagerNextIn(doc);
  if (!next) return false;
  next.click();
  return true;
}
