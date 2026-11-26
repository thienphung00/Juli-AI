"use client";

import { useState } from "react";

import { PairingRequestError, createSellerPairingCode, type SellerPairingCode } from "../lib/connector-pairing";
import { storeActiveShop } from "../lib/shop-session";
import { ShopsFetchError, createShopeeShop, type CreatedShopeeShop, type ShopeeShopInput } from "../lib/shops-client";

export type CreateShopeeShop = (accessToken: string, input: ShopeeShopInput) => Promise<CreatedShopeeShop>;
export type CreatePairingCode = (auth: { readonly token: string; readonly shopId: string }) => Promise<SellerPairingCode>;

const SHOPEE_ID = /^[0-9]{1,32}$/;

function shopError(e: unknown): string {
  const status = e instanceof ShopsFetchError ? e.status : 0;
  if (status === 409) return "Shop Shopee này đã được kết nối.";
  return "Không tạo được shop. Thử lại sau.";
}

function codeError(e: unknown): string {
  const status = e instanceof PairingRequestError ? e.status : 0;
  return status === 429 ? "Đã có 5 mã chưa dùng. Đợi mã cũ hết hạn (10 phút)." : "Không tạo được mã. Thử lại sau.";
}

/**
 * Owner #104 / #105: connect a Shopee shop from the connect screen. No Shopee OAuth yet, so the shop is
 * created by name (POST /v1/shops/shopee), becomes the acting shop, and the Juli Connector pairing code
 * (the same one Cài đặt › Juli Connector issues) is shown here.
 */
export function ConnectShopeeShop({
  accessToken,
  createShop = createShopeeShop,
  createCode = createSellerPairingCode,
  onCreated,
}: {
  readonly accessToken: string;
  readonly createShop?: CreateShopeeShop;
  readonly createCode?: CreatePairingCode;
  readonly onCreated?: (shop: CreatedShopeeShop) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [shopeeId, setShopeeId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shop, setShop] = useState<CreatedShopeeShop | null>(null);
  const [code, setCode] = useState<SellerPairingCode | null>(null);

  const issue = async (shopId: string) => {
    setBusy(true);
    setError(null);
    try {
      setCode(await createCode({ token: accessToken, shopId }));
    } catch (e) {
      setError(codeError(e));
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    const id = shopeeId.trim();
    if (id && !SHOPEE_ID.test(id)) {
      setError("Shopee shop ID chỉ gồm chữ số.");
      return;
    }
    setBusy(true);
    setError(null);
    let made: CreatedShopeeShop;
    try {
      made = await createShop(accessToken, { shop_name: name.trim(), shopee_shop_id: id || null });
    } catch (e) {
      setError(shopError(e));
      setBusy(false);
      return;
    }
    storeActiveShop({ id: made.id, name: made.shop_name });
    setShop(made);
    onCreated?.(made);
    await issue(made.id);
  };

  if (!open) {
    return (
      <button className="juli-btn juli-btn--secondary juli-btn--default" data-testid="connect-shopee-cta" onClick={() => setOpen(true)} type="button">
        Kết nối Shopee
      </button>
    );
  }

  return (
    <div className="connect-shop__shopee" data-testid="connect-shopee" style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 520 }}>
      {shop ? (
        <>
          <p style={{ margin: 0 }}>
            Shop Shopee: <strong>{shop.shop_name}</strong>
          </p>
          <ol style={{ margin: 0, paddingLeft: 20, fontSize: 14, lineHeight: 1.6 }}>
            <li>Cài tiện ích Juli Connector trên Chrome.</li>
            <li>Dán mã kết nối vào tiện ích.</li>
          </ol>
          {code ? (
            <p aria-label="Mã kết nối" style={{ margin: 0, fontSize: 14 }}>
              <strong style={{ fontSize: 22, letterSpacing: 2, fontFamily: "ui-monospace, monospace" }}>{code.code}</strong>
              <span> · dùng một lần, hết hạn sau {Math.round(code.ttl_seconds / 60)} phút</span>
            </p>
          ) : null}
          <div>
            <button className="juli-btn juli-btn--secondary juli-btn--default" disabled={busy} onClick={() => void issue(shop.id)} type="button">
              {busy ? "Đang tạo…" : "Tạo mã mới"}
            </button>
          </div>
        </>
      ) : (
        <>
          <label className="sd-field">
            <span className="sd-field__label">Tên shop</span>
            <input maxLength={200} onChange={(e) => setName(e.target.value)} type="text" value={name} />
          </label>
          <label className="sd-field">
            <span className="sd-field__label">Shopee shop ID</span>
            <input inputMode="numeric" maxLength={32} onChange={(e) => setShopeeId(e.target.value)} type="text" value={shopeeId} />
          </label>
          <div>
            <button className="juli-btn juli-btn--primary juli-btn--default" disabled={busy || !name.trim()} onClick={() => void submit()} type="button">
              {busy ? "Đang tạo…" : "Tạo shop"}
            </button>
          </div>
        </>
      )}
      {error ? (
        <p aria-live="assertive" className="connect-shop__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
