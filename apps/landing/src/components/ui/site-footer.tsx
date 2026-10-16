import Link from "next/link";

import { COMPANY, DEMO_URL, FOOTER_COMPANY_LINKS, FOOTER_PRODUCT_LINKS } from "../../lib/site";
import { CookieSettingsButton } from "../cookie-settings-button";
import { BrandMark } from "./brand";

/**
 * Site footer (D44, Main.dc.html): brand + one-line description with the
 * company and MST, three link columns (Sản phẩm · Công ty · Pháp lý), the
 * registered address and ©. No social links (D43.8); no headings (column
 * titles are `<p>`, seo README rule 4).
 */
export function SiteFooter() {
  return (
    <footer className="ui-footer">
      <div className="ui-footer__inner ui-container">
        <div className="ui-footer__brand">
          <BrandMark size="footer" />
          <p className="ui-footer__about">Trợ lý AI vận hành cho nhà bán TMĐT.</p>
          <address className="ui-footer__company" data-testid="footer-company">
            <span>
              {COMPANY.name} · MST {COMPANY.taxId}
            </span>
            <span>{COMPANY.address}</span>
            <a className="ui-footer__link" href={`mailto:${COMPANY.email}`}>
              {COMPANY.email}
            </a>
          </address>
        </div>
        <nav aria-label="Sản phẩm Juli" className="ui-footer__col">
          <p className="ui-footer__title">Sản phẩm</p>
          {FOOTER_PRODUCT_LINKS.map((page) => (
            <Link className="ui-footer__link" href={page.href} key={page.href}>
              {page.href === "/san-pham" ? "Tổng quan" : page.label}
            </Link>
          ))}
        </nav>
        <nav aria-label="Liên kết chân trang" className="ui-footer__col">
          <p className="ui-footer__title">Công ty</p>
          {FOOTER_COMPANY_LINKS.map((page) => (
            <Link className="ui-footer__link" href={page.href} key={page.href}>
              {page.label}
            </Link>
          ))}
          <a className="ui-footer__link" href={DEMO_URL}>
            Xem demo
          </a>
        </nav>
        <nav aria-label="Liên kết pháp lý" className="ui-footer__col">
          <p className="ui-footer__title">Pháp lý</p>
          <Link className="ui-footer__link" href="/privacy">
            Chính sách bảo mật
          </Link>
          <Link className="ui-footer__link" href="/terms">
            Điều khoản dịch vụ
          </Link>
          <CookieSettingsButton />
        </nav>
      </div>
      <div className="ui-footer__bottom ui-container">
        <p>© 2026 {COMPANY.name}</p>
      </div>
    </footer>
  );
}
