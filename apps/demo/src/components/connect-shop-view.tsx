"use client";

import { useEffect, useState } from "react";

import type { AuthSession } from "../lib/supabase-auth";
import { decodeJwtPayload } from "../lib/supabase-auth";
import { ShopsFetchError, fetchShops, type Shop } from "../lib/shops-client";

interface ConnectShopViewProps {
  session: AuthSession;
  /** Injectable for tests; defaults to the real `GET /v1/shops` client. */
  loadShops?: (accessToken: string) => Promise<Shop[]>;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; shops: Shop[] };

function describeError(error: unknown): string {
  if (error instanceof ShopsFetchError) {
    if (error.status === 401) {
      return "Không tìm thấy tài khoản của bạn trong hệ thống (Lỗi 401). Đây là hạn chế đã biết cho tài khoản Google mới — vui lòng thử lại sau hoặc liên hệ hỗ trợ.";
    }
    return `Không thể tải danh sách shop (Lỗi ${error.status}).`;
  }
  return "Không thể kết nối tới máy chủ để tải danh sách shop. Vui lòng thử lại.";
}

export function ConnectShopView({
  session,
  loadShops = fetchShops,
}: ConnectShopViewProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selectedShopId, setSelectedShopId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    loadShops(session.accessToken)
      .then((shops) => {
        if (cancelled) return;
        setState({ status: "ready", shops });
        setSelectedShopId(shops[0]?.id ?? null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({ status: "error", message: describeError(error) });
      });

    return () => {
      cancelled = true;
    };
    // session.accessToken is the only input this effect depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.accessToken]);

  const email =
    (decodeJwtPayload(session.accessToken)?.email as string | undefined) ??
    null;

  return (
    <section aria-labelledby="connect-shop-title" className="connect-shop">
      <p className="demo-kicker">Kết nối TikTok Shop</p>
      <h1 className="demo-title" id="connect-shop-title">
        Kết nối TikTok Shop
      </h1>
      {email && (
        <p className="connect-shop__identity">
          Bạn đã đăng nhập bằng <strong>{email}</strong>.
        </p>
      )}

      {state.status === "loading" && (
        <p role="status" aria-label="Đang kiểm tra tài khoản" aria-live="polite">
          Đang kiểm tra tài khoản của bạn…
        </p>
      )}

      {state.status === "error" && (
        <p role="alert" aria-live="assertive" className="connect-shop__error">
          {state.message}
        </p>
      )}

      {state.status === "ready" && (
        <ConnectShopReady
          onSelectShop={setSelectedShopId}
          selectedShopId={selectedShopId}
          shops={state.shops}
        />
      )}
    </section>
  );
}

function ConnectShopReady({
  onSelectShop,
  selectedShopId,
  shops,
}: {
  onSelectShop: (shopId: string) => void;
  selectedShopId: string | null;
  shops: Shop[];
}) {
  if (shops.length === 0) {
    return (
      <div className="connect-shop__empty">
        <p>Bạn chưa kết nối shop TikTok nào.</p>
        <button
          aria-disabled="true"
          className="juli-btn juli-btn--secondary juli-btn--default"
          data-testid="connect-tiktok-shop-cta"
          onClick={(event) => event.preventDefault()}
          type="button"
        >
          Kết nối TikTok Shop
        </button>
        <p className="connect-shop__disclaimer">
          Kết nối TikTok Shop thật đang được hoàn thiện — nút này chưa thực
          hiện thao tác nào.
        </p>
      </div>
    );
  }

  const selectedShop =
    shops.find((shop) => shop.id === selectedShopId) ?? shops[0];

  return (
    <div className="connect-shop__ready">
      {shops.length > 1 && (
        <div
          role="radiogroup"
          aria-label="Chọn shop bạn đang thao tác"
          className="connect-shop__picker"
        >
          {shops.map((shop) => (
            <label className="connect-shop__picker-option" key={shop.id}>
              <input
                checked={shop.id === selectedShopId}
                name="active-shop"
                onChange={() => onSelectShop(shop.id)}
                type="radio"
                value={shop.id}
              />
              {shop.shop_name}
            </label>
          ))}
        </div>
      )}

      {selectedShop && (
        <p className="connect-shop__active-shop">
          Bạn đang thao tác trên: <strong>{selectedShop.shop_name}</strong>
        </p>
      )}

      <p className="connect-shop__disclaimer">
        Kết nối TikTok Shop thật (đồng bộ đơn hàng, sản phẩm) đang được hoàn
        thiện — chưa có thao tác nào ở đây thay đổi shop thật của bạn.
      </p>
    </div>
  );
}
