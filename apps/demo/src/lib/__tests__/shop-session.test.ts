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
    window.localStorage.clear();
  });

  it("round-trips the selected shop through localStorage (survives new tabs, P11)", () => {
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
    window.localStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, "{not json");
    expect(readActiveShop()).toBeNull();

    window.localStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ name: "no id" }));
    expect(readActiveShop()).toBeNull();
  });

  it("clearActiveShop removes the record from both stores", () => {
    storeActiveShop({ id: "shop-1", name: "Shop 1" });
    window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "shop-old", name: "Old" }));
    clearActiveShop();
    expect(readActiveShop()).toBeNull();
    expect(window.localStorage.getItem(ACTIVE_SHOP_STORAGE_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(ACTIVE_SHOP_STORAGE_KEY)).toBeNull();
  });

  it("migrates a shop an older build left in sessionStorage", () => {
    window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "shop-1", name: "Shop 1" }));
    expect(readActiveShop()).toEqual({ id: "shop-1", name: "Shop 1" });
    expect(window.localStorage.getItem(ACTIVE_SHOP_STORAGE_KEY)).not.toBeNull();
    expect(window.sessionStorage.getItem(ACTIVE_SHOP_STORAGE_KEY)).toBeNull();
  });
});
