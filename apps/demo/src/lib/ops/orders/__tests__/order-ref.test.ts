import { describe, expect, it } from "vitest";

import { hexToBytes, importOrderRefKey, orderRef } from "../order-ref";

/** The vectors are pinned in `tests/unit/test_shopee_orders_parser.py` and `test_ops_shopee_orders.py` too. */
describe("order_ref", () => {
  it("is HMAC-SHA256 of the trimmed, upper-cased id, 32 hex characters, like the Python lanes", async () => {
    const key = await importOrderRefKey(new TextEncoder().encode("key"));
    expect(await orderRef("2610AAAAAA0001", key)).toBe("45fc017608554811b91b3b4040801ee2");
    expect(await orderRef("  2610aaaaaa0001 ", key)).toBe("45fc017608554811b91b3b4040801ee2");
    const shop = await importOrderRefKey(new TextEncoder().encode("synthetic-shop-key"));
    expect(await orderRef("2610ABCDEF0001", shop)).toBe("7a067ff446e9d13be7ce845574683cfb");
  });

  it("changes with the key and never contains the id", async () => {
    const one = await importOrderRefKey(new TextEncoder().encode("one"));
    const two = await importOrderRefKey(new TextEncoder().encode("two"));
    const a = await orderRef("2610AAAAAA0001", one);
    expect(a).not.toBe(await orderRef("2610AAAAAA0001", two));
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(a.toUpperCase()).not.toContain("2610AAAAAA0001");
  });

  it("reads a hex key and refuses anything else", () => {
    expect(Array.from(hexToBytes("00ff10"))).toEqual([0, 255, 16]);
    expect(() => hexToBytes("xyz")).toThrow();
    expect(() => hexToBytes("abc")).toThrow();
  });
});
