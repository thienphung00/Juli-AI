import { afterEach, describe, expect, it } from "vitest";

import {
  ACTIVE_SHOP_STORAGE_KEY,
  clearActiveShop,
  readActiveShop,
  storeActiveShop,
} from "../shop-session";

describe("shop-session — the acting shop the signed-in surfaces send as X-Shop-Id", () => {
  afterEach(() => {
    window.sessionStorage.clear();
  });

  it("round-trips the selected shop through sessionStorage", () => {
    storeActiveShop({ id: "1862f13b-de2c-4fae-a4ad-70298cead913", name: "Sandbox Shop" });

    expect(readActiveShop()).toEqual({
      id: "1862f13b-de2c-4fae-a4ad-70298cead913",
      name: "Sandbox Shop",
    });
  });

  it("returns null when nothing was stored", () => {
    expect(readActiveShop()).toBeNull();
  });

  it("returns null (never throws, never invents) for a corrupt stored value", () => {
    window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, "{not json");
    expect(readActiveShop()).toBeNull();

    window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ name: "no id" }));
    expect(readActiveShop()).toBeNull();
  });

  it("clearActiveShop removes the record", () => {
    storeActiveShop({ id: "shop-1", name: "Shop 1" });
    clearActiveShop();
    expect(readActiveShop()).toBeNull();
  });
});
