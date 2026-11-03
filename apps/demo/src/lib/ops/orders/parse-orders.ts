import { IGNORED, MAX_UPLOAD_LINES, ORDER_MONEY, READ, REQUIRED, SHEET } from "./columns";
import { orderRef } from "./order-ref";
import { readColumns } from "./xlsx-columns";

/**
 * The order export (Đơn hàng › Xuất) -> PII-free `order_lines`, in the browser: the TypeScript
 * twin of `scripts/shopee_exports/orders.py` (read its docstring for the layout facts). The
 * parity fixture (`__fixtures__/orders-synthetic.xlsx` + `.expected.json`, built by the Python
 * test) keeps both parsers producing the same rows.
 *
 * - header allowlist first; any unknown header stops the load before a value is read;
 * - the buyer's columns (name, phone, address, comment, note, tracking id ...) are never decoded;
 * - the order id becomes `order_ref` the moment its row is read; the raw id is kept nowhere;
 * - every error names a column or a count, never a cell value.
 */

export class UnknownColumnError extends Error {
  constructor(public readonly column: string) {
    super(column);
    this.name = "UnknownColumnError";
  }
}
export class OrderLayoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OrderLayoutError";
  }
}
export class UnknownStatusError extends Error {
  constructor(public readonly status: string) {
    super(status);
    this.name = "UnknownStatusError";
  }
}

export type OrderStatusName = "delivered" | "cancelled" | "in_transit" | "refunded_accepted" | "refunded_not_received";
export type PromoKind = "none" | "voucher" | "discount" | "flash_sale" | "bundle" | "add_on";

/** One line as posted to `POST /v1/ops/shops/{id}/shopee/orders/upload` (the `order_lines` row). */
export interface OrderLineRow {
  order_ref: string;
  line_no: number;
  ordered_at: string;
  status: OrderStatusName;
  sku?: string;
  variation_sku?: string;
  qty: number;
  returned_qty: number;
  original_price: number;
  deal_price: number;
  seller_subsidy: number;
  shopee_subsidy: number;
  shop_voucher_share: number;
  platform_voucher_share: number;
  bundle_discount: number;
  promo_kind: PromoKind;
  buyer_shipping_fee: number;
  bank_promo: number;
  fee_fixed?: number;
  fee_service?: number;
  fee_payment?: number;
  completed_at?: string;
  paid_at?: string;
}

/** Order-level totals kept for the preview and reconciliation; never posted. */
export interface OrderSummary {
  status: OrderStatusName;
  lines: number;
  ordered_at: string;
  order_value: number;
  buyer_total: number;
  gmv: number;
  shop_voucher: number;
  platform_voucher: number;
  paid: boolean;
  fees_filled: boolean;
}

export interface ParsedOrders {
  rows: OrderLineRow[];
  /** order_ref -> summary. */
  orders: Record<string, OrderSummary>;
  /** Normalised raw status text (dates replaced by DATE) -> lines. */
  rawStatusCounts: Record<string, number>;
  /** Headers whose cell values were decoded; never contains a buyer column. */
  valueColumnsRead: string[];
  ignoredHeaders: string[];
}

const PROFIT = new Set<OrderStatusName>(["delivered", "refunded_accepted"]);
const STATUS_PREFIXES: readonly (readonly [string, OrderStatusName])[] = [
  ["hoàn thành", "delivered"],
  ["đã giao", "delivered"],
  ["người mua xác nhận đã nhận được hàng", "delivered"],
  ["đã hủy", "cancelled"],
  ["đang hủy", "cancelled"],
  ["chưa thanh toán", "in_transit"],
  ["chờ xác nhận", "in_transit"],
  ["chờ lấy hàng", "in_transit"],
  ["chờ giao hàng", "in_transit"],
  ["đang giao", "in_transit"],
  ["đang vận chuyển", "in_transit"],
  ["đang xử lý", "in_transit"],
  ["cần xử lý", "in_transit"],
  ["đã xử lý", "in_transit"],
  ["đã gửi hàng", "in_transit"],
  ["đang chuẩn bị", "in_transit"],
];
const DATE_IN_TEXT = /\d{4}-\d{2}-\d{2}/g;
const NUMBER = /^-?\d+(\.\d+)?$/;
const TIME = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?$/;
const ACCEPTED = "chấp thuận";

const normal = (text: string): string => text.normalize("NFC").trim();
const clip = (text: string, width: number): string => Array.from(text).slice(0, width).join("");

export function mapStatus(raw: string, returnStatus: string | null | undefined, delivered: boolean): OrderStatusName {
  const text = normal(raw).toLowerCase();
  const status = STATUS_PREFIXES.find(([prefix]) => text.startsWith(prefix))?.[1];
  if (status === undefined) throw new UnknownStatusError(clip(normal(raw).replace(DATE_IN_TEXT, "DATE"), 120));
  if (status !== "cancelled" && returnStatus && normal(returnStatus).toLowerCase().includes(ACCEPTED)) {
    return delivered ? "refunded_accepted" : "refunded_not_received";
  }
  return status;
}

/** A cell as integer cents; null for empty or "-". More than two significant decimals is an error. */
export function cents(text: string | null | undefined, column: string): number | null {
  if (text === null || text === undefined) return null;
  const cell = text.trim();
  if (cell === "" || cell === "-") return null;
  if (!NUMBER.test(cell)) throw new OrderLayoutError(`column "${column}": a cell is not a plain number`);
  const negative = cell.startsWith("-");
  const [whole, fraction = ""] = cell.replace("-", "").split(".");
  if (/[1-9]/.test(fraction.slice(2))) throw new OrderLayoutError(`column "${column}": a cell has more than two decimals`);
  const value = Number(whole) * 100 + Number(fraction.slice(0, 2).padEnd(2, "0"));
  return negative ? -value : value;
}

/** `YYYY-MM-DD hh:mm[:ss]` -> `YYYY-MM-DDThh:mm:ss`; null for empty or "-". */
export function stamp(text: string | null | undefined, column: string): string | null {
  if (text === null || text === undefined) return null;
  const cell = text.trim();
  if (cell === "" || cell === "-") return null;
  const match = TIME.exec(cell);
  if (!match) throw new OrderLayoutError(`column "${column}": a cell is not a date and time`);
  const [, y, mo, d, h, mi, s = "00"] = match;
  const probe = new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s)));
  const same =
    probe.getUTCFullYear() === Number(y) &&
    probe.getUTCMonth() === Number(mo) - 1 &&
    probe.getUTCDate() === Number(d) &&
    probe.getUTCHours() === Number(h) &&
    probe.getUTCMinutes() === Number(mi) &&
    probe.getUTCSeconds() === Number(s);
  if (!same) throw new OrderLayoutError(`column "${column}": a cell is not a valid date and time`);
  return `${y}-${mo}-${d}T${h}:${mi}:${s}`;
}

/** `total` cut into cents proportional to `weights`; integer arithmetic, largest remainder, ties to the earlier line. */
export function splitByWeight(total: number, weights: readonly number[]): number[] {
  if (weights.length === 0) throw new Error("no lines to split over");
  const ZERO = BigInt(0);
  let shares = weights.map((w) => BigInt(w));
  if (shares.reduce((a, b) => a + b, ZERO) <= ZERO) shares = shares.map(() => BigInt(1));
  const sum = shares.reduce((a, b) => a + b, ZERO);
  const whole = BigInt(total);
  const parts = shares.map((share) => [(whole * share) / sum, (whole * share) % sum] as const);
  const pieces = parts.map(([quotient]) => quotient);
  const left = Number(whole - pieces.reduce((a, b) => a + b, ZERO));
  const order = parts.map((_, i) => i).sort((a, b) => (parts[a][1] === parts[b][1] ? a - b : parts[a][1] > parts[b][1] ? -1 : 1));
  for (const i of order.slice(0, left)) pieces[i] += BigInt(1);
  return pieces.map(Number);
}

const money = (value: number): number => (value % 100 === 0 ? value / 100 : Number((value / 100).toFixed(2)));

function chooseColumns(header: string[]): number[] {
  const names = header.map(normal);
  for (const name of names) {
    if (!(name in READ) && !IGNORED.has(name)) throw new UnknownColumnError(name);
  }
  const missing = REQUIRED.find((name) => !names.includes(name));
  if (missing !== undefined) throw new UnknownColumnError(`missing column ${missing}`);
  return names.flatMap((name, i) => (name in READ ? [i] : []));
}

function distinct(values: (number | null)[], column: string): number {
  const nonzero = new Set(values.filter((v): v is number => v !== null && v !== 0));
  if (nonzero.size > 1) throw new OrderLayoutError(`column "${column}": differs between the lines of one order`);
  return nonzero.size === 1 ? [...nonzero][0] : 0;
}

function first<T>(values: (T | null)[], column: string): T | null {
  const present = new Set(values.filter((v): v is T => v !== null));
  if (present.size > 1) throw new OrderLayoutError(`column "${column}": differs between the lines of one order`);
  return present.size === 1 ? [...present][0] : null;
}

type Cells = Record<string, string | null | undefined>;

interface Line {
  sku: string | null;
  variation_sku: string | null;
  qty: number;
  returned_qty: number;
  original: number;
  deal: number;
  seller_subsidy: number;
  shopee_subsidy: number;
  status: OrderStatusName;
  gmv: number;
}

function compareLines(a: Line, b: Line): number {
  const keys: [string | number, string | number][] = [
    [a.sku ?? "", b.sku ?? ""],
    [a.variation_sku ?? "", b.variation_sku ?? ""],
    [a.original, b.original],
    [a.deal, b.deal],
    [a.qty, b.qty],
  ];
  for (const [x, y] of keys) if (x !== y) return x < y ? -1 : 1;
  return 0;
}

export async function parseOrderExport(bytes: Uint8Array, key: CryptoKey): Promise<ParsedOrders> {
  const sheet = await readColumns(bytes, SHEET, chooseColumns);
  const names = sheet.header.map(normal);
  const result: ParsedOrders = {
    rows: [],
    orders: {},
    rawStatusCounts: {},
    valueColumnsRead: [...sheet.valueColumnsRead].map((i) => names[i]).sort(),
    ignoredHeaders: names.filter((n) => IGNORED.has(n)).sort(),
  };
  const column: Record<string, number> = {};
  const label: Record<string, string> = {};
  names.forEach((name, i) => {
    if (name in READ) {
      column[READ[name][0]] = i;
      label[READ[name][0]] = name;
    }
  });

  const byOrder = new Map<string, Cells[]>();
  for (const row of sheet.rows) {
    const cells: Cells = {};
    for (const [field, index] of Object.entries(column)) cells[field] = row.get(index);
    const orderId = cells.order_id;
    if (orderId === null || orderId === undefined || orderId.trim() === "") continue;
    const ref = await orderRef(orderId, key);
    const lines = byOrder.get(ref);
    if (lines) lines.push(cells);
    else byOrder.set(ref, [cells]);
  }

  for (const [ref, cellRows] of byOrder) {
    const ordered = first(cellRows.map((c) => stamp(c.ordered_at, label.ordered_at)), "date");
    if (ordered === null) throw new OrderLayoutError(`column "${label.ordered_at}": an order has no date`);
    const delivered = cellRows.some((c) => stamp(c.delivered_at, "delivered") !== null);
    const completed = first(cellRows.map((c) => stamp(c.completed_at, label.completed_at)), "c");
    const paid = first(cellRows.map((c) => stamp(c.paid_at, label.paid_at)), "p");
    const orderLevel: Record<string, number> = {};
    for (const field of ORDER_MONEY) {
      if (field in column) orderLevel[field] = distinct(cellRows.map((c) => cents(c[field], label[field])), label[field]);
    }
    const lines: Line[] = cellRows.map((c) => {
      const qtyCents = cents(c.qty, label.qty) ?? 0;
      if (qtyCents % 100 !== 0 || qtyCents < 0) throw new OrderLayoutError(`column "${label.qty}": not a whole quantity`);
      const qty = qtyCents / 100;
      const original = cents(c.original_price, label.original_price) ?? 0;
      const deal = cents(c.deal_price, label.deal_price) ?? 0;
      const rawStatus = c.status ?? "";
      const status = mapStatus(rawStatus, c.return_status, delivered || completed !== null);
      const text = normal(rawStatus).replace(DATE_IN_TEXT, "DATE");
      result.rawStatusCounts[text] = (result.rawStatusCounts[text] ?? 0) + 1;
      const returned = cents(c.returned_qty, label.returned_qty) ?? 0;
      return {
        sku: clip((c.sku ?? "").trim(), 120) || null,
        variation_sku: clip((c.variation_sku ?? "").trim(), 120) || null,
        qty,
        returned_qty: returned / 100,
        original,
        deal,
        seller_subsidy: cents(c.seller_subsidy, label.seller_subsidy) ?? 0,
        shopee_subsidy: cents(c.shopee_subsidy, label.shopee_subsidy) ?? 0,
        status,
        gmv: deal * qty,
      };
    });
    // Canonical numbering: independent of the order the export lists the lines in.
    lines.sort(compareLines);
    const weights = lines.map((ln) => ln.gmv);
    const profit = lines.some((ln) => PROFIT.has(ln.status));
    const shares: Record<string, number[]> = {};
    for (const field of ["shop_voucher", "platform_voucher", "shopee_combo", "shop_combo", "bank_promo", "buyer_shipping_fee", "fee_fixed", "fee_service", "fee_payment"]) {
      shares[field] = splitByWeight(orderLevel[field] ?? 0, weights);
      if (shares[field].reduce((a, b) => a + b, 0) !== (orderLevel[field] ?? 0)) {
        throw new OrderLayoutError(`column "${label[field] ?? field}": split does not add up`);
      }
    }
    const feesFilled = profit && ["fee_fixed", "fee_service", "fee_payment"].some((f) => (orderLevel[f] ?? 0) !== 0);
    const gmv = weights.reduce((a, b) => a + b, 0);
    result.orders[ref] = {
      status: lines[0].status,
      lines: lines.length,
      ordered_at: ordered,
      order_value: money(orderLevel.order_value ?? 0),
      buyer_total: money(orderLevel.buyer_total ?? 0),
      gmv: money(gmv),
      shop_voucher: money(orderLevel.shop_voucher ?? 0),
      platform_voucher: money(orderLevel.platform_voucher ?? 0),
      paid: paid !== null,
      fees_filled: feesFilled,
    };
    lines.forEach((ln, n) => {
      const bundle = shares.shop_combo[n];
      const voucher = shares.shop_voucher[n];
      const kind: PromoKind = bundle > 0 ? "bundle" : ln.seller_subsidy > 0 || ln.original > ln.deal ? "discount" : voucher > 0 ? "voucher" : "none";
      const row: OrderLineRow = {
        order_ref: ref,
        line_no: n,
        ordered_at: ordered,
        status: ln.status,
        qty: ln.qty,
        returned_qty: ln.returned_qty,
        original_price: money(ln.original),
        deal_price: money(ln.deal),
        seller_subsidy: money(ln.seller_subsidy),
        shopee_subsidy: money(ln.shopee_subsidy),
        shop_voucher_share: money(voucher),
        platform_voucher_share: money(shares.platform_voucher[n] + shares.shopee_combo[n]),
        bundle_discount: money(bundle),
        promo_kind: kind,
        buyer_shipping_fee: money(shares.buyer_shipping_fee[n]),
        bank_promo: money(shares.bank_promo[n]),
      };
      if (ln.sku) row.sku = ln.sku;
      if (ln.variation_sku) row.variation_sku = ln.variation_sku;
      if (completed !== null) row.completed_at = completed;
      if (paid !== null) row.paid_at = paid;
      if (feesFilled) {
        row.fee_fixed = money(shares.fee_fixed[n]);
        row.fee_service = money(shares.fee_service[n]);
        row.fee_payment = money(shares.fee_payment[n]);
      }
      result.rows.push(row);
    });
  }
  return result;
}

/** The lines cut into upload bodies: one order month at a time, at most {@link MAX_UPLOAD_LINES} lines each. */
export function toUploadChunks(rows: readonly OrderLineRow[]): OrderLineRow[][] {
  const byMonth = new Map<string, OrderLineRow[]>();
  for (const row of rows) {
    const month = row.ordered_at.slice(0, 7);
    const list = byMonth.get(month);
    if (list) list.push(row);
    else byMonth.set(month, [row]);
  }
  const chunks: OrderLineRow[][] = [];
  for (const month of [...byMonth.keys()].sort()) {
    const lines = [...(byMonth.get(month) ?? [])].sort((a, b) =>
      a.ordered_at !== b.ordered_at ? (a.ordered_at < b.ordered_at ? -1 : 1) : a.order_ref !== b.order_ref ? (a.order_ref < b.order_ref ? -1 : 1) : a.line_no - b.line_no,
    );
    for (let at = 0; at < lines.length; at += MAX_UPLOAD_LINES) chunks.push(lines.slice(at, at + MAX_UPLOAD_LINES));
  }
  return chunks;
}

/** Counts for the preview: lines, orders, the date span and orders per mapped status. */
export interface OrderPreview {
  lines: number;
  orders: number;
  firstDay: string;
  lastDay: string;
  statusCounts: Record<OrderStatusName, number>;
  chunks: number;
}

export function previewOf(parsed: ParsedOrders): OrderPreview {
  const statusCounts: Record<OrderStatusName, number> = { delivered: 0, cancelled: 0, in_transit: 0, refunded_accepted: 0, refunded_not_received: 0 };
  const days: string[] = [];
  for (const order of Object.values(parsed.orders)) {
    statusCounts[order.status] += 1;
    days.push(order.ordered_at.slice(0, 10));
  }
  days.sort();
  return {
    lines: parsed.rows.length,
    orders: Object.keys(parsed.orders).length,
    firstDay: days[0] ?? "",
    lastDay: days[days.length - 1] ?? "",
    statusCounts,
    chunks: toUploadChunks(parsed.rows).length,
  };
}
