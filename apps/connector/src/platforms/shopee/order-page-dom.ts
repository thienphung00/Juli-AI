// The order page's DOM (`/portal/sale/order/<order_id>`, Chi tiết đơn hàng), read by the page hook
// for the order page reader (Connector 0.3.32, batch-1123-a C1 + C3; captured read-only 2026-11-23).
//
// The page's own order call loads before the hook can see it, so the reader reads what the page
// SHOWS, nothing else:
// - each line (`.product-item.product`): its "Phân loại" and "SKU phân loại" (`.product-meta`)
//   and the line total (the last ₫ amount of the line) -- a combo whose order answer names no SKU
//   gets its SKUs from here (C1);
// - the "Doanh thu" block (`.income-container`): every `.income-item` as label
//   (`.income-label-text`) and amount (`.income-value`) -- the per-order income (C3).
// No buyer name, address, phone, chat or note is read. Nothing is clicked: when the breakdown is
// folded ("Xem chi tiết doanh thu") only its totals are there and the reader takes what it sees.

import type { PageItem } from "./orders-map";

/** "₫65.735", "-₫35.700", "− 16.000 ₫" -> 65735, -35700, -16000; undefined without digits. */
export function moneyOf(raw: string | null | undefined): number | undefined {
  const t = (raw ?? "").replace(/\s+/g, " ").trim();
  const digits = t.replace(/[^\d]/g, "");
  if (!digits) return undefined;
  const negative = /^[-−–]|\(\s*[-−–]\s*\)|[-−–]\s*₫|₫\s*[-−–]/.test(t);
  const n = Number(digits);
  return negative ? -n : n;
}

/** A label's tooltip (icon svg with an inline <style>, its popper text): never part of the label. */
const LABEL_NOISE = ".eds-popover, .payment-tooltip, .payment-detail-tooltip-popper, svg, style, script";

/**
 * 0.3.34 (C-H4, live DOM 24/11): an income label is its element's OWN text. `.income-label-text`
 * holds the text node ("Doanh Thu Đơn Hàng ") and then the tooltip `div.eds-popover.payment-tooltip`,
 * whose svg `<style>` and popper text leaked into `textContent`, so no label matched. Its direct
 * text nodes first; a label drawn inside a child element (not a tooltip) is read from there.
 */
export function ownLabelText(el: Element): string {
  const clean = (t: string) => t.replace(/\s+/g, " ").trim();
  const direct = clean(
    Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent ?? "")
      .join(" "),
  );
  if (direct) return direct;
  const parts: string[] = [];
  const walk = (node: Node): void => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === 3) parts.push(child.textContent ?? "");
      else if (child.nodeType === 1 && !(child as Element).matches(LABEL_NOISE)) walk(child);
    }
  };
  walk(el);
  return clean(parts.join(" "));
}

/** Every income row the order page shows, in page order: `{name, amount}` (the income mapper's shape). */
export function incomeItemsIn(doc: Document): { name: string; amount: number }[] {
  const out: { name: string; amount: number }[] = [];
  for (const row of Array.from(doc.querySelectorAll(".income-container .income-item"))) {
    const label = row.querySelector(".income-label-text");
    const name = label ? ownLabelText(label) : undefined;
    // the row's own value (a tooltip's breakdown can carry amounts of its own)
    const value = Array.from(row.querySelectorAll(".income-value")).find((el) => !el.closest(LABEL_NOISE));
    const amount = moneyOf(value?.textContent);
    if (name && amount !== undefined) out.push({ name: name.slice(0, 120), amount });
  }
  return out;
}

const VARIATION = /^Phân loại\s*:\s*(.+)$/i;
const SKU = /^SKU phân loại\s*:\s*(.+)$/i;
const QTY = /^[x×]?\s*(\d{1,4})$/i;
const MONEY = /[-−–]?\s*₫\s*[\d.,]+|[\d.,]+\s*₫/;

/** The meta lines of one product line: its child elements' texts, else its text split by line. */
function metaLines(meta: Element): string[] {
  const children = Array.from(meta.children).map((c) => (c.textContent ?? "").replace(/\s+/g, " ").trim());
  const lines = children.length > 0 ? children : (meta.textContent ?? "").split(/\n/);
  return lines.map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);
}

/** The product lines the order page shows, in page order. */
export function pageItemsIn(doc: Document): PageItem[] {
  const out: PageItem[] = [];
  for (const line of Array.from(doc.querySelectorAll(".product-item.product"))) {
    const item: PageItem = {};
    const meta = line.querySelector(".product-meta");
    for (const text of meta ? metaLines(meta) : []) {
      const sku = SKU.exec(text)?.[1]?.trim();
      const variation = VARIATION.exec(text)?.[1]?.trim();
      if (sku && !item.sku) item.sku = sku.slice(0, 120);
      else if (variation && !item.variationName) item.variationName = variation.slice(0, 120);
    }
    // the line total: the last element of the line (outside its meta) that shows one ₫ amount
    const cells = Array.from(line.querySelectorAll("*")).filter((el) => el.children.length === 0 && !el.closest(".product-meta"));
    const priced = cells.map((el) => el.textContent ?? "").filter((t) => MONEY.test(t) && (t.match(/₫/g) ?? []).length === 1);
    const total = moneyOf(priced[priced.length - 1]);
    if (total !== undefined && total > 0) item.lineTotal = total;
    // the quantity: a cell (outside the meta) that is a bare count ("2", "x2")
    const counts = cells.map((el) => QTY.exec((el.textContent ?? "").trim())?.[1]).filter((q): q is string => q !== undefined);
    const qty = counts.length > 0 ? Number(counts[counts.length - 1]) : undefined;
    if (qty !== undefined && qty > 0) item.qty = qty;
    out.push(item);
  }
  return out;
}
