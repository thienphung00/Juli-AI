import Link from "next/link";

import { COMPANY, DEMO_URL, SITE_PAGES } from "../lib/site";
import { CookieSettingsButton } from "./cookie-settings-button";
import { SiteLogo } from "./site-logo";

export function SiteFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-footer__brand">
        <SiteLogo height={26} />
        <p className="lp-footer__tagline">Trợ lý AI cho người bán TikTok Shop</p>
        <address className="lp-footer__company" data-testid="footer-company">
          <strong>{COMPANY.name}</strong>
          <span>Mã số thuế: {COMPANY.taxId}</span>
          <span>{COMPANY.address}</span>
        </address>
      </div>
      <nav aria-label="Liên kết chân trang" className="lp-footer__nav">
        {SITE_PAGES.map((page) => (
          <Link className="lp-footer__link" href={page.href} key={page.href}>
            {page.label}
          </Link>
        ))}
        <a className="lp-footer__link" href={DEMO_URL}>
          Trải nghiệm Demo
        </a>
        <a className="lp-footer__link" href={`mailto:${COMPANY.email}`}>
          {COMPANY.email}
        </a>
      </nav>
      <nav aria-label="Liên kết pháp lý" className="lp-footer__nav lp-footer__nav--legal">
        <Link className="lp-footer__link" href="/privacy">
          Chính sách bảo mật
        </Link>
        <Link className="lp-footer__link" href="/terms">
          Điều khoản dịch vụ
        </Link>
        <CookieSettingsButton />
      </nav>
      <p className="lp-footer__legal">© 2026 Juli AI</p>
    </footer>
  );
}
