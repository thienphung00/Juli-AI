import Link from "next/link";

import { DEMO_URL, SITE_PAGES } from "../lib/site";
import { CtaLink } from "./cta-link";
import { SiteLogo } from "./site-logo";

/**
 * One header for every page: links to real pages (not `/` anchors), so the
 * same nav works on every route. Desktop shows the nav inline; below 48rem a
 * CSS-only `<details>` menu carries the same links (no client JS).
 */
export function LandingHeader() {
  return (
    <header className="lp-header">
      <Link aria-label="Juli AI, trang chủ" className="lp-header__brand" href="/">
        <SiteLogo height={30} />
      </Link>
      <nav aria-label="Điều hướng chính" className="lp-header__nav">
        {SITE_PAGES.map((page) => (
          <Link className="lp-header__link" href={page.href} key={page.href}>
            {page.label}
          </Link>
        ))}
      </nav>
      <div className="lp-header__end">
        <CtaLink data-testid="header-demo-cta" href={DEMO_URL} size="default">
          Xem demo
        </CtaLink>
        <details className="lp-header__menu">
          <summary className="lp-header__menu-button">Menu</summary>
          <nav aria-label="Menu trên điện thoại" className="lp-header__menu-panel">
            {SITE_PAGES.map((page) => (
              <Link className="lp-header__link" href={page.href} key={page.href}>
                {page.label}
              </Link>
            ))}
          </nav>
        </details>
      </div>
    </header>
  );
}
