"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { ConnectShopView } from "../../../components/connect-shop-view";
import { readAuthSession, type AuthSession } from "../../../lib/supabase-auth";

/**
 * "Kết nối TikTok Shop" — the centre of this slice (ADR-094 decision 3). Only
 * reachable with a real Supabase session; a visitor with none is sent back to
 * the landing honestly rather than shown a broken or fixture screen.
 */
export default function ConnectShopPage() {
  const [session, setSession] = useState<AuthSession | null | undefined>(
    undefined,
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSession(readAuthSession());
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  if (session === undefined) {
    return null;
  }

  if (session === null) {
    return (
      <section aria-labelledby="connect-shop-no-session-title" className="demo-placeholder">
        <p className="demo-kicker">Kết nối TikTok Shop</p>
        <h1 id="connect-shop-no-session-title">Bạn chưa đăng nhập</h1>
        <p role="alert" aria-live="assertive">
          Bạn chưa đăng nhập bằng Google nên chưa thể xem màn hình kết nối
          shop.
        </p>
        <Link className="demo-placeholder__recovery" href="/">
          Về trang chào mừng để đăng nhập
        </Link>
      </section>
    );
  }

  return <ConnectShopView session={session} />;
}
