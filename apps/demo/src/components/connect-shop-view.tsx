"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { AuthSession } from "../lib/supabase-auth";
import { storeActiveShop } from "../lib/shop-session";
import { ACTIONS_DESTINATION_LABEL } from "../lib/destination-copy";
import { decodeJwtPayload } from "../lib/supabase-auth";
import { ShopsFetchError, fetchShops, type Shop } from "../lib/shops-client";
import {
  startTikTokConnect,
  type TikTokOAuthStart,
} from "../lib/tiktok-connect-client";

/** `dictionary.md` `auth.connect_shop.redirecting` (issue #1970). */
export const CONNECT_REDIRECTING_COPY = "Đang chuyển bạn tới TikTok…";
/** `dictionary.md` `auth.connect_shop.failed` (issue #1970). */
export const CONNECT_FAILED_COPY =
  "Không thể bắt đầu kết nối TikTok. Vui lòng thử lại.";

interface ConnectShopViewProps {
  session: AuthSession;
  /** Injectable for tests; defaults to the real `GET /v1/shops` client. */
  loadShops?: (accessToken: string) => Promise<Shop[]>;
  /** Injectable for tests; defaults to the real `GET /v1/auth/tiktok/start` client. */
  startConnect?: (accessToken: string) => Promise<TikTokOAuthStart>;
  /**
   * Injectable for tests only. jsdom cannot perform a real navigation, and the
   * production default is the browser's own — this component never builds a
   * TikTok URL itself, it only goes where the server-signed one points.
   */
  navigate?: (url: string) => void;
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
  startConnect = startTikTokConnect,
  navigate = (url) => window.location.assign(url),
}: ConnectShopViewProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selectedShopId, setSelectedShopId] = useState<string | null>(null);

  // Issue #1909: the selection made here is what every signed-in surface
  // sends as `X-Shop-Id` — persist it (default first shop, then whatever
  // the seller picks) so Decisions and the run view act on the same shop
  // this screen told the seller they are acting on.
  const selectShop = (shop: Shop) => {
    setSelectedShopId(shop.id);
    storeActiveShop({ id: shop.id, name: shop.shop_name });
  };

  useEffect(() => {
    let cancelled = false;

    loadShops(session.accessToken)
      .then((shops) => {
        if (cancelled) return;
        setState({ status: "ready", shops });
        if (shops[0]) {
          setSelectedShopId(shops[0].id);
          storeActiveShop({ id: shops[0].id, name: shops[0].shop_name });
        } else {
          setSelectedShopId(null);
        }
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
          accessToken={session.accessToken}
          navigate={navigate}
          onSelectShop={selectShop}
          selectedShopId={selectedShopId}
          shops={state.shops}
          startConnect={startConnect}
        />
      )}
    </section>
  );
}

/**
 * The real connect control (issue #1970). It asks the backend for an authorize
 * URL and goes there; it never assembles a TikTok URL client-side, because the
 * only thing that makes that URL safe is the server-signed `state` naming the
 * signed-in seller — a client-built one would carry no owner and the callback
 * would refuse it.
 */
function ConnectTikTokShopButton({
  accessToken,
  navigate,
  startConnect,
  variant,
}: {
  accessToken: string;
  navigate: (url: string) => void;
  startConnect: (accessToken: string) => Promise<TikTokOAuthStart>;
  variant: "primary" | "secondary";
}) {
  const [phase, setPhase] = useState<"idle" | "starting" | "error">("idle");

  const begin = async () => {
    setPhase("starting");
    try {
      const { authorize_url } = await startConnect(accessToken);
      navigate(authorize_url);
    } catch {
      // Deliberately no detail from the error: a failure here tells the seller
      // nothing actionable beyond "try again", and the backend's 401/503 text
      // is operator vocabulary.
      setPhase("error");
    }
  };

  return (
    <>
      <button
        className={`juli-btn juli-btn--${variant} juli-btn--default`}
        data-testid="connect-tiktok-shop-cta"
        disabled={phase === "starting"}
        onClick={begin}
        type="button"
      >
        Kết nối TikTok Shop
      </button>
      {phase === "starting" && (
        <p aria-live="polite" role="status">
          {CONNECT_REDIRECTING_COPY}
        </p>
      )}
      {phase === "error" && (
        <p
          aria-live="assertive"
          className="connect-shop__error"
          role="alert"
        >
          {CONNECT_FAILED_COPY}
        </p>
      )}
    </>
  );
}

function ConnectShopReady({
  accessToken,
  navigate,
  onSelectShop,
  selectedShopId,
  shops,
  startConnect,
}: {
  accessToken: string;
  navigate: (url: string) => void;
  onSelectShop: (shop: Shop) => void;
  selectedShopId: string | null;
  shops: Shop[];
  startConnect: (accessToken: string) => Promise<TikTokOAuthStart>;
}) {
  if (shops.length === 0) {
    return (
      <div className="connect-shop__empty">
        <p>Bạn chưa kết nối shop TikTok nào.</p>
        <ConnectTikTokShopButton
          accessToken={accessToken}
          navigate={navigate}
          startConnect={startConnect}
          variant="primary"
        />
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
                onChange={() => onSelectShop(shop)}
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

      {/* Narrowed by #1970, not deleted. The half that said connecting a real
          shop "đang được hoàn thiện" is no longer true — this screen connects
          it. The half that matters downstream still is: the Actions surface is
          replay, so nothing the seller does after this changes their shop. */}
      <p className="connect-shop__disclaimer">
        Các thao tác ở {ACTIONS_DESTINATION_LABEL} vẫn là bản minh họa — chưa có
        thao tác nào thay đổi shop thật của bạn.
      </p>

      <Link className="juli-btn juli-btn--primary juli-btn--default" href="/decisions">
        Đi tới {ACTIONS_DESTINATION_LABEL}
      </Link>

      {/* A seller can own more than one shop; connecting another is the same
          handshake, so the same control is offered rather than a second path. */}
      <ConnectTikTokShopButton
        accessToken={accessToken}
        navigate={navigate}
        startConnect={startConnect}
        variant="secondary"
      />
    </div>
  );
}
