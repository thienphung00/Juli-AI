import type { OrderLinesUploaded, OrderRefKeyResponse } from "../types";
import { hexToBytes, importOrderRefKey } from "./order-ref";
import { parseOrderExport, toUploadChunks, type OrderLineRow, type ParsedOrders } from "./parse-orders";

/**
 * The browser side of the order upload, as three small steps the page strings together:
 *
 * 1. {@link prepareOrderUpload}: fetch the shop's `order_ref` key (a short-lived, `no-store`,
 *    audited endpoint), parse the workbook with it, and drop it. The key lives in this function's
 *    scope only: it is never put in React state, `localStorage`, `sessionStorage`, a cookie, a
 *    URL or a log, and it is not part of the result.
 * 2. the page shows the counts and waits for the operator;
 * 3. {@link postOrderLines}: post the chunks, in order, one request each.
 *
 * Nothing but the allowlisted, hashed lines is ever posted.
 */

export interface OrderUploadApi {
  orderRefKey(shopId: string): Promise<OrderRefKeyResponse>;
  uploadOrderLines(shopId: string, lines: OrderLineRow[]): Promise<OrderLinesUploaded>;
}

export async function prepareOrderUpload(
  bytes: Uint8Array,
  shopId: string,
  api: Pick<OrderUploadApi, "orderRefKey">,
): Promise<ParsedOrders> {
  const issued = await api.orderRefKey(shopId);
  if (issued.algorithm !== "HMAC-SHA256") throw new Error("Khóa băm mã đơn hàng không đúng loại.");
  // The CryptoKey is non-extractable; the hex string is not kept past this call.
  const key = await importOrderRefKey(hexToBytes(issued.order_ref_key));
  return parseOrderExport(bytes, key);
}

export interface PostProgress {
  readonly posted: number;
  readonly total: number;
  readonly duplicates: number;
}

export async function postOrderLines(
  parsed: ParsedOrders,
  shopId: string,
  api: Pick<OrderUploadApi, "uploadOrderLines">,
  onProgress?: (progress: PostProgress) => void,
): Promise<PostProgress> {
  const chunks = toUploadChunks(parsed.rows);
  let posted = 0;
  let duplicates = 0;
  for (const chunk of chunks) {
    const result = await api.uploadOrderLines(shopId, chunk);
    posted += result.lines;
    if (result.duplicate) duplicates += 1;
    onProgress?.({ posted, total: parsed.rows.length, duplicates });
  }
  return { posted, total: parsed.rows.length, duplicates };
}
