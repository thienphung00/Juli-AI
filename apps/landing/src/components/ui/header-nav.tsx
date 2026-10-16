"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type FocusEvent, type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";

import { HEADER_NAV, PRODUCT_MENU } from "../../lib/site";
import { Icon, type IconName } from "./icon";

/** Active when the path is the item's `match` or below it. */
export function isActiveNav(pathname: string | null, match: string): boolean {
  if (!pathname) return false;
  return pathname === match || pathname.startsWith(`${match}/`);
}

/** The header item that opens the product dropdown instead of linking. */
const PRODUCT_MATCH = "/san-pham";

const PRODUCT_ICONS: Record<(typeof PRODUCT_MENU)[number]["href"], IconName> = {
  "/san-pham": "grid",
  "/san-pham/phan-tich-shop": "chart",
  "/san-pham/de-xuat-va-thuc-thi": "check-square",
  "/san-pham/do-luong-gmv": "target",
};

export interface HeaderNavProps {
  label: string;
  className?: string;
  /** Override the router's path (tests, previews). */
  pathname?: string;
  /** `bar` = desktop header (floating panel) · `panel` = inside the mobile menu (inline group). */
  variant?: "bar" | "panel";
}

/** The header links with `aria-current="page"` on the current section. */
export function HeaderNav({ label, className, pathname, variant = "bar" }: HeaderNavProps) {
  const routerPath = usePathname();
  const current = pathname ?? routerPath;
  return (
    <nav aria-label={label} className={className}>
      {HEADER_NAV.map((item) => {
        if (item.match === PRODUCT_MATCH) {
          return <ProductMenu current={current} key={item.href} label={item.label} variant={variant} />;
        }
        const active = isActiveNav(current, item.match);
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className="ui-header__link"
            href={item.href}
            key={item.href}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

interface ProductMenuProps {
  label: string;
  current: string | null;
  variant: "bar" | "panel";
}

/**
 * "Sản phẩm" dropdown (D45.1): a disclosure button + a panel of the four
 * product pages. The panel is always rendered (the links are in the server
 * HTML, crawlable) and shown by `data-open` in CSS. Escape closes it and
 * returns focus to the button; a click outside, focus leaving it (desktop) or
 * a route change closes it. "Open" is remembered for the path it was opened
 * on, so navigating away closes it without an effect.
 */
function ProductMenu({ label, current, variant }: ProductMenuProps) {
  const [openOn, setOpenOn] = useState<string | null | undefined>(undefined);
  const open = openOn !== undefined && openOn === current;
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = `ui-navmenu-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const active = isActiveNav(current, PRODUCT_MATCH);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpenOn(undefined);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const close = () => setOpenOn(undefined);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    close();
    buttonRef.current?.focus();
  };

  const onBlur = (event: FocusEvent<HTMLDivElement>) => {
    // Desktop only: tabbing past the last item closes the floating panel. In
    // the mobile menu the group stays open while the rest of the menu is read.
    if (variant !== "bar") return;
    const next = event.relatedTarget as Node | null;
    if (next && !rootRef.current?.contains(next)) close();
  };

  return (
    <div
      className={`ui-navmenu ui-navmenu--${variant}`}
      data-open={open ? "" : undefined}
      onBlur={onBlur}
      onKeyDown={onKeyDown}
      ref={rootRef}
    >
      <button
        aria-controls={panelId}
        aria-expanded={open}
        className="ui-header__link ui-navmenu__button"
        data-active={active ? "" : undefined}
        onClick={() => setOpenOn(open ? undefined : current)}
        ref={buttonRef}
        type="button"
      >
        {label}
        <Icon className="ui-navmenu__chevron" name="chevron-down" size={16} />
      </button>
      <div className="ui-navmenu__panel" id={panelId}>
        <ul className="ui-navmenu__list">
          {PRODUCT_MENU.map((item) => (
            <li key={item.href}>
              <Link
                aria-current={current === item.href ? "page" : undefined}
                className="ui-navmenu__item"
                href={item.href}
                onClick={close}
              >
                <span className="ui-navmenu__icon">
                  <Icon name={PRODUCT_ICONS[item.href]} size={18} strokeWidth={1.8} />
                </span>
                <span className="ui-navmenu__text">
                  <span className="ui-navmenu__label">{item.label}</span>
                  <span className="ui-navmenu__desc">{item.description}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/**
 * The mobile menu: a `<details>` disclosure (works without JS); the only JS
 * closes it after a client-side navigation, which `<details>` cannot know about.
 */
export function HeaderMenu({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const pathname = usePathname();
  useEffect(() => {
    if (ref.current) ref.current.open = false;
  }, [pathname]);
  return (
    <details className="ui-header__menu" ref={ref}>
      {children}
    </details>
  );
}
