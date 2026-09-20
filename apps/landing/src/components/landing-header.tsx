import Link from "next/link";

import { JuliLogo } from "@juli/brand";

import { DEMO_URL, SECTION_IDS } from "../lib/site";
import { CtaLink } from "./cta-link";

const NAV_LINKS = [
  { href: `#${SECTION_IDS.features}`, label: "Tính năng" },
  { href: `#${SECTION_IDS.comparison}`, label: "Giải pháp" },
  { href: `#${SECTION_IDS.contact}`, label: "Liên hệ" },
] as const;

export interface LandingHeaderProps {
  /**
   * The in-page section anchors only resolve on `/` — a legal page (`/privacy`,
   * `/terms`) has none of those sections, so it renders the brand + Demo CTA
   * without the dead anchor links instead of reusing this nav as-is.
   */
  showSectionNav?: boolean;
}

export function LandingHeader({ showSectionNav = true }: LandingHeaderProps) {
  return (
    <header className="lp-header">
      <Link aria-label="Juli AI, trang chủ" className="lp-header__brand" href="/">
        <JuliLogo size={30} />
      </Link>
      {showSectionNav ? (
        <nav aria-label="Điều hướng chính" className="lp-header__nav">
          {NAV_LINKS.map((link) => (
            <a className="lp-header__link" href={link.href} key={link.href}>
              {link.label}
            </a>
          ))}
        </nav>
      ) : null}
      <CtaLink data-testid="header-demo-cta" href={DEMO_URL} size="default">
        Dùng thử Demo
      </CtaLink>
    </header>
  );
}
