import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectShopView } from "../components/connect-shop-view";
import { PairingRequestError } from "../lib/connector-pairing";
import { readActiveShop } from "../lib/shop-session";
import { ShopsFetchError } from "../lib/shops-client";

/** Owner #104 / #105: the connect screen offers Shopee — a form, then the Connector pairing code on the same page. */

const session = { accessToken: "token-1", refreshToken: "r-1", expiresIn: 3600, tokenType: "bearer" };
const created = { id: "new-shopee", shop_name: "Shop Mẫu", platform: "shopee", shopee_shop_id: null };
const code = { code: "AB12CD", expires_at: "2026-11-26T10:10:00Z", ttl_seconds: 600 };

function view(createShopee = vi.fn().mockResolvedValue(created), createPairing = vi.fn().mockResolvedValue(code)) {
  render(<ConnectShopView createPairingCode={createPairing} createShopeeShop={createShopee} loadShops={vi.fn().mockResolvedValue([])} session={session} />);
  return { createShopee, createPairing };
}

async function openForm() {
  await userEvent.click(await screen.findByRole("button", { name: "Kết nối Shopee" }));
}

beforeEach(() => window.localStorage.clear());

describe("Kết nối Shopee", () => {
  it("creates the shop, makes it the active shop and shows its pairing code", async () => {
    const { createShopee, createPairing } = view();
    await openForm();
    await userEvent.type(screen.getByRole("textbox", { name: "Tên shop" }), "Shop Mẫu");
    await userEvent.click(screen.getByRole("button", { name: "Tạo shop" }));
    expect(await screen.findByLabelText("Mã kết nối")).toHaveTextContent("AB12CD");
    expect(screen.getByLabelText("Mã kết nối")).toHaveTextContent("hết hạn sau 10 phút");
    expect(createShopee).toHaveBeenCalledWith("token-1", { shop_name: "Shop Mẫu", shopee_shop_id: null });
    expect(createPairing).toHaveBeenCalledWith({ token: "token-1", shopId: "new-shopee" });
    expect(readActiveShop()).toEqual({ id: "new-shopee", name: "Shop Mẫu" });
  });

  it("sends the Shopee shop ID when given", async () => {
    const { createShopee } = view();
    await openForm();
    await userEvent.type(screen.getByRole("textbox", { name: "Tên shop" }), "Shop Mẫu");
    await userEvent.type(screen.getByRole("textbox", { name: "Shopee shop ID" }), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Tạo shop" }));
    await waitFor(() => expect(createShopee).toHaveBeenCalledWith("token-1", { shop_name: "Shop Mẫu", shopee_shop_id: "123456" }));
  });

  it("no name, no request", async () => {
    const { createShopee } = view();
    await openForm();
    expect(screen.getByRole("button", { name: "Tạo shop" })).toBeDisabled();
    expect(createShopee).not.toHaveBeenCalled();
  });

  it("an ID that is not digits is refused before any request", async () => {
    const { createShopee } = view();
    await openForm();
    await userEvent.type(screen.getByRole("textbox", { name: "Tên shop" }), "Shop Mẫu");
    await userEvent.type(screen.getByRole("textbox", { name: "Shopee shop ID" }), "shop-12");
    await userEvent.click(screen.getByRole("button", { name: "Tạo shop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Shopee shop ID chỉ gồm chữ số.");
    expect(createShopee).not.toHaveBeenCalled();
  });

  it("a shop already connected: says so, no code", async () => {
    const { createPairing } = view(vi.fn().mockRejectedValue(new ShopsFetchError(409)));
    await openForm();
    await userEvent.type(screen.getByRole("textbox", { name: "Tên shop" }), "Shop Mẫu");
    await userEvent.click(screen.getByRole("button", { name: "Tạo shop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Shop Shopee này đã được kết nối.");
    expect(createPairing).not.toHaveBeenCalled();
    expect(readActiveShop()).toBeNull();
  });

  it("a code that fails can be asked for again", async () => {
    const createPairing = vi.fn().mockRejectedValueOnce(new PairingRequestError(500)).mockResolvedValueOnce(code);
    view(undefined, createPairing);
    await openForm();
    await userEvent.type(screen.getByRole("textbox", { name: "Tên shop" }), "Shop Mẫu");
    await userEvent.click(screen.getByRole("button", { name: "Tạo shop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Không tạo được mã. Thử lại sau.");
    await userEvent.click(screen.getByRole("button", { name: "Tạo mã mới" }));
    expect(await screen.findByLabelText("Mã kết nối")).toHaveTextContent("AB12CD");
  });
});
