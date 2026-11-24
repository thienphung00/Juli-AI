// The order page's DOM (`/portal/sale/order/<order_id>`, Chi tiết đơn hàng), read by the page hook
// for the order page reader (Connector 0.3.32, batch-1123-a C1 + C3; captured read-only 2026-11-23).
//
// The page's own order call loads before the hook can see it, so the reader reads what the page
// SHOWS, nothing else:
// - each line (`.product-item.product`): its "Phân loại" and "SKU phân loại" (`.product-meta`)
//   and the line total (the last ₫ amount of the line) -- a combo whose order answer names no SKU
//   gets its SKUs from here (C1); a combo shows one `.bundle-deal-item` per sub-line (1124-b CONN);
// - the "Doanh thu" block (`.income-container`): every `.income-item` as label
//   (`.income-label-text`) and amount (`.income-value`) -- the per-order income (C3).
// No buyer name, address, phone, chat or note is read. Nothing is clicked: when the breakdown is
// folded ("Xem chi tiết doanh thu") only its totals are there and the reader takes what it sees.

import { type PageItem, plainLabel } from "./orders-map";

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

/**
 * batch-1124-a S1 (P-S3 capture, 24/11): the buyer's payment block ("Thanh toán của Người Mua":
 * Tổng tiền sản phẩm | Phí vận chuyển | Shopee Voucher | Mã giảm giá của Shop | Tổng tiền Thanh
 * toán) is outside `.income-container`. Only the two voucher rows are read (an ALLOWLIST of labels,
 * nothing else of the block). The block is found by its heading text and bounded by its total row;
 * each allowed label takes the first ₫ amount shown after it. The buyer-side shop voucher is NOT the
 * seller's cost (that is the income block's own row): it is posted apart, as `buyer_items`.
 */
const BUYER_HEADING = /^thanh toan cua nguoi mua$/;
const BUYER_TOTAL = /^tong tien thanh toan$/;
const BUYER_LABELS = /^(shopee voucher|ma giam gia cua shop)$/;

const plainText = plainLabel;

export function buyerItemsIn(doc: Document): { name: string; amount: number }[] {
  const leaves = Array.from(doc.querySelectorAll("body *")).filter((el) => el.children.length === 0 && !el.closest(LABEL_NOISE));
  const start = leaves.findIndex((el) => BUYER_HEADING.test(plainText(el.textContent ?? "")));
  if (start < 0) return [];
  const out: { name: string; amount: number }[] = [];
  let pending: string | undefined;
  for (const el of leaves.slice(start + 1)) {
    const raw = (el.textContent ?? "").replace(/\s+/g, " ").trim();
    if (!raw) continue;
    const key = plainText(raw);
    if (BUYER_TOTAL.test(key)) break;
    if (BUYER_LABELS.test(key)) {
      pending = raw.slice(0, 120);
      continue;
    }
    if (pending !== undefined && MONEY.test(raw)) {
      const amount = moneyOf(raw);
      if (amount !== undefined && !out.some((o) => plainText(o.name) === plainText(pending as string))) out.push({ name: pending, amount });
      pending = undefined;
    } else if (pending !== undefined && /[a-z]/.test(key)) {
      pending = undefined; // another label came first: that row shows no amount
    }
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

/** The "Phân loại" / "SKU phân loại" of one product line's meta. */
function readMeta(meta: Element | null, item: PageItem): void {
  for (const text of meta ? metaLines(meta) : []) {
    const sku = SKU.exec(text)?.[1]?.trim();
    const variation = VARIATION.exec(text)?.[1]?.trim();
    if (sku && !item.sku) item.sku = sku.slice(0, 120);
    else if (variation && !item.variationName) item.variationName = variation.slice(0, 120);
  }
}

/**
 * batch-1124-b CONN (P-CONN capture, 24/11): a combo's sub-line (`.order-payment-item.is-bundle >
 * .bundle-deal-items > .bundle-deal-item`): its `.product-item` meta, its unit list price (`.price`)
 * and quantity (`.qty`); the line total is price x quantity. The combo's `.subtotal` is not a line.
 */
function bundleItem(line: Element): PageItem {
  const item: PageItem = {};
  readMeta(line.querySelector(".product-item .product-meta"), item);
  const qty = Number(QTY.exec((line.querySelector(".qty")?.textContent ?? "").trim())?.[1]);
  if (Number.isInteger(qty) && qty > 0) item.qty = qty;
  const unit = moneyOf(line.querySelector(".price")?.textContent);
  if (unit !== undefined && unit > 0) {
    item.listPrice = unit;
    if (item.qty !== undefined) item.lineTotal = unit * item.qty;
  }
  return item;
}

/** The product lines the order page shows, in page order (a combo: one line per sub-line). */
export function pageItemsIn(doc: Document): PageItem[] {
  const out: PageItem[] = [];
  for (const line of Array.from(doc.querySelectorAll(".product-item.product, .bundle-deal-item"))) {
    if (line.matches(".bundle-deal-item")) {
      out.push(bundleItem(line));
      continue;
    }
    if (line.closest(".bundle-deal-item")) continue;
    const item: PageItem = {};
    readMeta(line.querySelector(".product-meta"), item);
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
