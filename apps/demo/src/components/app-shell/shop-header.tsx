"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import {
  CONNECT_SHOP_HREF,
  EMAIL_SIGN_IN_HREF,
  SETTINGS_HREF,
  SETTINGS_LABEL,
} from "../../lib/app-navigation";
import { DEMO_MODE_REPLAY_LABEL } from "../../lib/demo-mode-copy";
import { envelopeOf, type ShopReportState } from "../../lib/shop-report/shop-report-context";
import {
  EMAIL_SIGN_IN_LABEL,
  EMAIL_SIGN_IN_UNAVAILABLE_COPY,
  GOOGLE_SIGN_IN_UNAVAILABLE_COPY,
} from "../../lib/supabase-auth";
import { vnClock } from "../../lib/vn-format";

/**
 * The shell's header (ADR-109 decision 7): shop avatar (initials), shop name,
 * "TikTok Shop · <ngành> · <N> SKU" when known, and on the right
 * "Juli đang chạy · cập nhật HH:MM" from the report's `built_at` — omitted
 * when no report is loaded rather than invented. NO five-stage stepper here
 * (decision 8: it lives inside Quyết định only).
 *
 * The avatar opens the shop menu, which now holds what used to be header
 * controls and the fourth nav tab: Cài đặt, connect/switch shop, sign out —
 * and, for an anonymous visitor, Đăng nhập với Google, Đăng nhập bằng email
 * (AC-9.1, → `/auth/email`) and Làm mới Demo.
 */

export function shopInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "J";
  const letters = words.slice(0, 2).map((w) => Array.from(w)[0] ?? "");
  return letters.join("").toLocaleUpperCase("vi-VN");
}

/** "TikTok Shop · ngành · N SKU", each part only when known. */
export function shopSubline(details: { industry?: string | null; skuCount?: number | null }): string {
  const parts = ["TikTok Shop"];
  if (details.industry) parts.push(details.industry);
  if (typeof details.skuCount === "number" && details.skuCount > 0) {
    parts.push(`${details.skuCount.toLocaleString("vi-VN")} SKU`);
  }
  return parts.join(" · ");
}

export interface ShopHeaderProps {
  readonly state: ShopReportState;
  /**
   * Supabase authorize URL; `null` = not configured, `undefined` = not resolved
   * yet. The email item shares its fate (same two NEXT_PUBLIC_SUPABASE_* values).
   */
  readonly googleHref: string | null | undefined;
  readonly onRefreshDemo: () => void;
  readonly onSignOut: () => void;
}

function shopNameOf(state: ShopReportState): string | null {
  switch (state.status) {
    case "anonymous":
      return state.envelope?.report.shop_name ?? null;
    case "ready":
      return state.shop.name || state.envelope.report.shop_name || "Shop của bạn";
    case "loading":
    case "empty":
    case "error":
      return state.shop.name || "Shop của bạn";
    case "no-shop":
      return "Chưa chọn shop";
    default:
      return null;
  }
}

export function ShopHeader({ state, googleHref, onRefreshDemo, onSignOut }: ShopHeaderProps) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const anonymous = state.status === "anonymous";
  const signedIn = !anonymous && state.status !== "resolving";
  const name = shopNameOf(state);
  const envelope = envelopeOf(state);
  const updatedAt = vnClock(envelope?.built_at);
  const close = () => setOpen(false);

  return (
    <header className="shop-header" data-testid="shop-header">
      <div className="shop-header__shop" ref={rootRef}>
        <button
          aria-controls={menuId}
          aria-expanded={open}
          aria-label={name ? `Menu shop ${name}` : "Menu shop"}
          className="shop-avatar"
          onClick={() => setOpen((value) => !value)}
          ref={buttonRef}
          type="button"
        >
          <span aria-hidden="true">{shopInitials(name ?? "")}</span>
        </button>
        <div className="shop-header__identity">
          <p className="shop-header__name">
            {name ?? <span className="text-muted">Đang tải…</span>}
            {anonymous ? <span className="badge badge-pink">{DEMO_MODE_REPLAY_LABEL}</span> : null}
          </p>
          <p className="shop-header__sub">{shopSubline({})}</p>
        </div>
        <div className="shop-menu" hidden={!open} id={menuId}>
          <ul className="shop-menu__list">
            <li>
              <Link className="shop-menu__item" href={SETTINGS_HREF} onClick={close}>
                {SETTINGS_LABEL}
              </Link>
            </li>
            {signedIn ? (
              <>
                <li>
                  <Link className="shop-menu__item" href={CONNECT_SHOP_HREF} onClick={close}>
                    {state.status === "no-shop" ? "Kết nối TikTok Shop" : "Đổi shop"}
                  </Link>
                </li>
                <li>
                  <button
                    className="shop-menu__item"
                    onClick={() => {
                      close();
                      onSignOut();
                    }}
                    type="button"
                  >
                    Đăng xuất
                  </button>
                </li>
              </>
            ) : (
              <>
                <li>
                  {googleHref ? (
                    <a className="shop-menu__item" href={googleHref}>
                      Đăng nhập với Google
                    </a>
                  ) : (
                    <span
                      aria-disabled="true"
                      className="shop-menu__item shop-menu__item--disabled"
                      role="link"
                      title={GOOGLE_SIGN_IN_UNAVAILABLE_COPY}
                    >
                      Đăng nhập với Google
                    </span>
                  )}
                </li>
                <li>
                  {googleHref ? (
                    <Link className="shop-menu__item" href={EMAIL_SIGN_IN_HREF} onClick={close}>
                      {EMAIL_SIGN_IN_LABEL}
                    </Link>
                  ) : (
                    <span
                      aria-disabled="true"
                      className="shop-menu__item shop-menu__item--disabled"
                      role="link"
                      title={EMAIL_SIGN_IN_UNAVAILABLE_COPY}
                    >
                      {EMAIL_SIGN_IN_LABEL}
                    </span>
                  )}
                </li>
                <li>
                  <button
                    className="shop-menu__item"
                    onClick={() => {
                      close();
                      onRefreshDemo();
                    }}
                    type="button"
                  >
                    Làm mới Demo
                  </button>
                </li>
              </>
            )}
          </ul>
        </div>
      </div>
      {updatedAt ? (
        <p className="shop-header__status">
          <span
            aria-hidden="true"
            className={anonymous ? "status-dot status-dot--idle" : "status-dot"}
          />
          {anonymous
            ? `Dữ liệu mẫu · cập nhật ${updatedAt}`
            : `Juli đang chạy · cập nhật ${updatedAt}`}
        </p>
      ) : null}
    </header>
  );
}
