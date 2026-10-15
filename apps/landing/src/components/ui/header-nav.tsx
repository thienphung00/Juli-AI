"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { HEADER_NAV } from "../../lib/site";

/** Active when the path is the item's `match` or below it. */
export function isActiveNav(pathname: string | null, match: string): boolean {
  if (!pathname) return false;
  return pathname === match || pathname.startsWith(`${match}/`);
}

export interface HeaderNavProps {
  label: string;
  className?: string;
  /** Override the router's path (tests, previews). */
  pathname?: string;
}

/** The header links with `aria-current="page"` on the current section. */
export function HeaderNav({ label, className, pathname }: HeaderNavProps) {
  const routerPath = usePathname();
  const current = pathname ?? routerPath;
  return (
    <nav aria-label={label} className={className}>
      {HEADER_NAV.map((item) => {
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
