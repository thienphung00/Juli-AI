// `order_ref`: the keyed hash that stands for a Shopee order everywhere after the browser —
// HMAC-SHA256 of `"shopee-order|" + id.trim().toUpperCase()`, first 32 hex characters, with the
// shop's key (GET /v1/ingest/order-ref-key). The same function as the Ops upload page
// (apps/demo lib/ops/orders/order-ref.ts), `scripts.shopee_exports.parse.order_ref` and
// `services/ingest/order_ref.py`, so the affiliate lines match the order export's.

export function hexToBytes(hex: string): Uint8Array {
  if (!/^(?:[0-9a-f]{2})+$/i.test(hex)) throw new Error("order_ref key is not hex");
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export async function importOrderRefKey(hex: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", hexToBytes(hex) as BufferSource, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
}

export async function orderRef(orderId: string, key: CryptoKey): Promise<string> {
  const message = new TextEncoder().encode(`shopee-order|${orderId.trim().toUpperCase()}`);
  const signature = await crypto.subtle.sign("HMAC", key, message);
  return Array.from(new Uint8Array(signature), (b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 32);
}
