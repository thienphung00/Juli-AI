/**
 * `order_ref`: the keyed hash that stands for an order everywhere after the browser. HMAC-SHA256
 * of `"shopee-order|" + id.trim().toUpperCase()`, first 32 hex characters, with the shop's key
 * (`GET /v1/ops/shops/{id}/shopee/orders/ref-key`). The same function as
 * `scripts.shopee_exports.parse.order_ref` and `services/ingest/order_ref.py`, so the affiliate
 * lane and the order export agree on an order. The raw id never leaves this function's caller.
 */

export function hexToBytes(hex: string): Uint8Array {
  if (!/^(?:[0-9a-f]{2})+$/i.test(hex)) throw new Error("order_ref key is not hex");
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function importOrderRefKey(key: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", key as BufferSource, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
}

export async function orderRef(orderId: string, key: CryptoKey): Promise<string> {
  const message = new TextEncoder().encode(`shopee-order|${orderId.trim().toUpperCase()}`);
  const signature = await crypto.subtle.sign("HMAC", key, message);
  return toHex(new Uint8Array(signature)).slice(0, 32);
}
