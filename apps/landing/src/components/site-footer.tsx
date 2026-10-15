import Link from "next/link";

import { COMPANY, DEMO_URL, FOOTER_PRODUCT_LINKS, SITE_PAGES } from "../lib/site";
import { CookieSettingsButton } from "./cookie-settings-button";
import { SiteLogo } from "./site-logo";

/** No social links (D43.8): the footer names the company and links real pages only. */
export function SiteFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-footer__brand">
        <SiteLogo height={26} />
        <p className="lp-footer__tagline">Trợ lý AI vận hành cho nhà bán TikTok Shop</p>
        <address className="lp-footer__company" data-testid="footer-company">
          <strong>{COMPANY.name}</strong>
          <span>Mã số thuế: {COMPANY.taxId}</span>
          <span>{COMPANY.address}</span>
        </address>
      </div>
      <div className="lp-footer__columns">
        <nav aria-label="Sản phẩm Juli" className="lp-footer__nav">
          <p className="lp-footer__nav-title">Sản phẩm</p>
          {FOOTER_PRODUCT_LINKS.map((page) => (
            <Link className="lp-footer__link" href={page.href} key={page.href}>
              {page.label}
            </Link>
          ))}
        </nav>
        <nav aria-label="Liên kết chân trang" className="lp-footer__nav">
          <p className="lp-footer__nav-title">Công ty</p>
          {SITE_PAGES.filter((page) => page.href !== "/san-pham").map((page) => (
            <Link className="lp-footer__link" href={page.href} key={page.href}>
              {page.label}
            </Link>
          ))}
          <a className="lp-footer__link" href={DEMO_URL}>
            Xem demo
          </a>
          <a className="lp-footer__link" href={`mailto:${COMPANY.email}`}>
            {COMPANY.email}
          </a>
        </nav>
        <nav aria-label="Liên kết pháp lý" className="lp-footer__nav lp-footer__nav--legal">
          <p className="lp-footer__nav-title">Pháp lý</p>
          <Link className="lp-footer__link" href="/privacy">
            Chính sách bảo mật
          </Link>
          <Link className="lp-footer__link" href="/terms">
            Điều khoản dịch vụ
          </Link>
          <CookieSettingsButton />
        </nav>
      </div>
      <p className="lp-footer__legal">© 2026 {COMPANY.name}</p>
    </footer>
  );
}
