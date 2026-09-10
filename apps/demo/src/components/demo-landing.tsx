"use client";

import { useEffect, useState } from "react";

import { Button } from "@juli/ui";

import { readEntryMode, writeEntryMode } from "../lib/entry-mode";
import { buildGoogleAuthorizeUrl } from "../lib/supabase-auth";
import { HomeLauncher } from "./home-launcher";

/**
 * The landing's two deliberately asymmetric doors (ADR-094, PUI-DESIGN §1).
 * "Dùng thử Demo" flips local, session-scoped state only — it calls nothing.
 * "Đăng nhập với Google" is a real, full-page link to Supabase Auth; its href
 * is resolved on mount (never during SSR, so client and server agree on the
 * first paint) and is `null` — an honest disabled state, not a broken link —
 * when Supabase env is not configured in this build.
 */
export function DemoLanding() {
  const [hasEnteredReplay, setHasEnteredReplay] = useState(false);
  const [googleHref, setGoogleHref] = useState<string | null | undefined>(
    undefined,
  );

  // Deferred via setTimeout(0) rather than calling the setter synchronously
  // in the effect body — the same pattern `demo-state.tsx` already uses for
  // its own browser-storage read (`react-hooks/set-state-in-effect`).
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (readEntryMode() === "replay") {
        setHasEnteredReplay(true);
      }
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setGoogleHref(
        buildGoogleAuthorizeUrl(`${window.location.origin}/auth/callback`),
      );
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  if (hasEnteredReplay) {
    return <HomeLauncher />;
  }

  const handleEnterReplay = () => {
    writeEntryMode("replay");
    setHasEnteredReplay(true);
  };

  const googleConfigured = googleHref !== null && googleHref !== undefined;

  return (
    <section aria-labelledby="landing-title" className="demo-landing">
      <p className="demo-kicker">Chào mừng đến với Juli</p>
      <h1 className="demo-title" id="landing-title">
        Chọn cách bạn muốn bắt đầu
      </h1>

      <div className="demo-landing__doors" role="group" aria-label="Chọn lối vào">
        <article className="demo-landing__door">
          <p className="demo-landing__door-eyebrow">Xem thử, không cần tài khoản</p>
          <h2>Dùng thử Demo</h2>
          <p>
            Đây là bản minh họa dựng từ dữ liệu mẫu đã ghi lại sẵn — không
            phải dữ liệu shop thật của bạn, và không tạo tài khoản nào.
          </p>
          <Button onClick={handleEnterReplay} type="button">
            Dùng thử Demo
          </Button>
        </article>

        <article className="demo-landing__door demo-landing__door--google">
          <p className="demo-landing__door-eyebrow">Tài khoản thật của bạn</p>
          <h2>Đăng nhập với Google</h2>
          <p>
            Tạo tài khoản Juli thật bằng Google, sau đó đến màn hình Kết nối
            TikTok Shop.
          </p>
          {googleConfigured ? (
            <a className="demo-landing__google-link juli-btn juli-btn--secondary juli-btn--default" href={googleHref}>
              Đăng nhập với Google
            </a>
          ) : (
            <span
              aria-disabled="true"
              className="demo-landing__google-link demo-landing__google-link--disabled juli-btn juli-btn--secondary juli-btn--default"
              role="link"
              aria-label="Đăng nhập với Google — chưa cấu hình trong môi trường này"
            >
              Đăng nhập với Google
            </span>
          )}
        </article>
      </div>
    </section>
  );
}
