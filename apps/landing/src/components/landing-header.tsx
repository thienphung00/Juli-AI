import Link from "next/link";

import { JuliLogo } from "@juli/brand";

import { DEMO_URL, SITE_PAGES } from "../lib/site";
import { CtaLink } from "./cta-link";

/**
 * One header for every page: links to real pages (not `/` anchors), so the
 * same nav works on `/product`, `/about`, `/contact` and the legal pages.
 */
export function LandingHeader() {
  return (
    <header className="lp-header">
      <Link aria-label="Juli AI, trang chủ" className="lp-header__brand" href="/">
        <JuliLogo size={30} />
      </Link>
      <nav aria-label="Điều hướng chính" className="lp-header__nav">
        {SITE_PAGES.map((page) => (
          <Link className="lp-header__link" href={page.href} key={page.href}>
            {page.label}
          </Link>
        ))}
      </nav>
      <CtaLink data-testid="header-demo-cta" href={DEMO_URL} size="default">
        Dùng thử Demo
      </CtaLink>
    </header>
  );
}
