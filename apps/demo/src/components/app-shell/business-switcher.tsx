"use client";

import { useEffect, useId, useRef, useState } from "react";

import {
  businessOfShop,
  fetchBusinesses,
  type Business,
  type BusinessShop,
} from "../../lib/businesses-client";
import { PLATFORM_LABEL, type ShopPlatform } from "../../lib/shop-platform";
import { storeActiveBusiness, storeActiveShop } from "../../lib/shop-session";

/**
 * P101 W1: the header switcher, Doanh nghiệp ▾ → Shop ▾ (platform mark beside each shop), from
 * `GET /v1/businesses`. Picking a shop uses the existing active-shop mechanism (`X-Shop-Id` from
 * `shop-session`) and reloads, like the reviewer's shop switch. Rendered only when there is
 * something to switch (two shops or two businesses).
 */

export const BUSINESS_SWITCH_LABEL = "Doanh nghiệp";
export const SHOP_SWITCH_LABEL = "Shop";

export function PlatformMark({ platform }: { readonly platform: ShopPlatform }) {
  return (
    <span
      aria-label={PLATFORM_LABEL[platform]}
      className={`platform-mark platform-mark--${platform}`}
      role="img"
      title={PLATFORM_LABEL[platform]}
    >
      {platform === "shopee" ? "S" : "T"}
    </span>
  );
}

function defaultSwitch(shop: BusinessShop, business: Business): void {
  storeActiveBusiness(business.id);
  storeActiveShop({ id: shop.id, name: shop.name });
  window.location.assign("/");
}

interface BusinessSwitcherProps {
  readonly token: string;
  readonly activeShopId: string | null;
  readonly fetchImpl?: typeof fetch;
  readonly onSwitch?: (shop: BusinessShop, business: Business) => void;
}

type Open = "business" | "shop" | null;

export function BusinessSwitcher({ token, activeShopId, fetchImpl, onSwitch = defaultSwitch }: BusinessSwitcherProps) {
  const [businesses, setBusinesses] = useState<readonly Business[] | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const businessMenuId = useId();
  const shopMenuId = useId();

  useEffect(() => {
    let live = true;
    void fetchBusinesses(token, fetchImpl).then((found) => {
      if (live) setBusinesses(found);
    });
    return () => {
      live = false;
    };
  }, [token, fetchImpl]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(null);
    };
    const onPointer = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  if (!businesses) return null;
  const shopCount = businesses.reduce((total, b) => total + b.shops.length, 0);
  if (businesses.length < 2 && shopCount < 2) return null;
  const current = businessOfShop(businesses, activeShopId);
  if (!current) return null;
  const activeShop = current.shops.find((s) => s.id === activeShopId) ?? null;

  const pick = (shop: BusinessShop, business: Business) => {
    setOpen(null);
    if (shop.id !== activeShopId) onSwitch(shop, business);
  };

  return (
    <div className="business-switcher" data-testid="business-switcher" ref={rootRef}>
      <div className="business-switcher__group">
        <button
          aria-controls={businessMenuId}
          aria-expanded={open === "business"}
          aria-label={`${BUSINESS_SWITCH_LABEL}: ${current.name}`}
          className="business-switcher__button"
          onClick={() => setOpen((value) => (value === "business" ? null : "business"))}
          type="button"
        >
          <span className="business-switcher__value">{current.name}</span>
          <span aria-hidden="true">▾</span>
        </button>
        <ul className="shop-menu business-switcher__menu" hidden={open !== "business"} id={businessMenuId}>
          {businesses.map((business) => {
            const first = business.shops[0];
            return (
              <li key={business.id ?? `shop-${first?.id ?? business.name}`}>
                <button
                  aria-current={business === current ? "true" : undefined}
                  className="shop-menu__item"
                  disabled={!first}
                  onClick={() => (first ? pick(first, business) : undefined)}
                  type="button"
                >
                  {business.name}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      <div className="business-switcher__group">
        <button
          aria-controls={shopMenuId}
          aria-expanded={open === "shop"}
          aria-label={`${SHOP_SWITCH_LABEL}: ${activeShop?.name ?? ""}`}
          className="business-switcher__button"
          onClick={() => setOpen((value) => (value === "shop" ? null : "shop"))}
          type="button"
        >
          {activeShop ? <PlatformMark platform={activeShop.platform} /> : null}
          <span className="business-switcher__value">{activeShop?.name ?? SHOP_SWITCH_LABEL}</span>
          <span aria-hidden="true">▾</span>
        </button>
        <ul className="shop-menu business-switcher__menu" hidden={open !== "shop"} id={shopMenuId}>
          {current.shops.map((shop) => (
            <li key={shop.id}>
              <button
                aria-current={shop.id === activeShopId ? "true" : undefined}
                className="shop-menu__item business-switcher__shop"
                onClick={() => pick(shop, current)}
                type="button"
              >
                <PlatformMark platform={shop.platform} />
                {shop.name}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
