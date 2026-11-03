import { readFileSync } from "node:fs";
import { join } from "node:path";

import { hexToBytes, importOrderRefKey } from "../order-ref";
import type { OrderLineRow } from "../parse-orders";

/** The parity fixtures built by `tests/unit/test_shopee_orders_parser.py` (synthetic values). */
// vitest runs from apps/demo (see `pnpm test`).
const dir = `${join(process.cwd(), "src/lib/ops/orders/__fixtures__")}/`;

export const PLAIN = new Uint8Array(readFileSync(`${dir}orders-synthetic.xlsx`));
export const POISONED = new Uint8Array(readFileSync(`${dir}orders-poisoned.xlsx`));

export interface Golden {
  key_utf8: string;
  rows: OrderLineRow[];
  orders: Record<string, unknown>;
  raw_status_counts: Record<string, number>;
  value_columns_read: string[];
  ignored_headers: string[];
}

export const GOLDEN: Golden = JSON.parse(readFileSync(`${dir}orders-synthetic.expected.json`, "utf-8"));

export const KEY_HEX = Array.from(new TextEncoder().encode(GOLDEN.key_utf8), (b) => b.toString(16).padStart(2, "0")).join("");

export const importKey = () => importOrderRefKey(hexToBytes(KEY_HEX));

/** Strings the buyer columns carry in the fixtures; they must appear in no output. */
export const CANARIES = [
  "CANARY-nguoi-mua-Tran-Thi-B",
  "CANARY-nguoi-nhan-Le-Van-C",
  "CANARY-0909123456",
  "CANARY-12-duong-Nguyen-Hue",
  "CANARY-TP-Ho-Chi-Minh",
  "CANARY-binh-luan-giao-gio-hanh-chinh",
  "CANARY-SPXVN0123456789",
  "CANARY-PKG-77",
  "CANARY-ghi-chu-noi-bo",
  "CANARY-ten-san-pham-bi-mat",
];
/** The raw order ids of the fixtures. */
export const RAW_ORDER_IDS = ["P-0001", "P-0002", "P-0003", "P-0004", "P-0005", "P-0006", "P-0007", "P-0008", "P-0009"];
